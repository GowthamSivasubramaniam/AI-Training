"""
RAG System for PostgreSQL Documentation
Processes Word documents, creates embeddings, and enables semantic search
"""

import numpy as np
from typing import List, Dict, Tuple

import nltk
from nltk.tokenize import sent_tokenize

import torch
from transformers import BertTokenizer, BertModel
from transformers import AutoTokenizer, AutoModelForCausalLM
import chromadb
from chromadb.config import Settings

try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

from PyPDF2 import PdfReader

LLM_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
llm = AutoModelForCausalLM.from_pretrained(
    LLM_MODEL,
    device_map="auto",
    torch_dtype=torch.float16
)

class DocumentProcessor:    
    def __init__(self):
        self.documents = []
    
    def load_pdf_document(self, file_path: str) -> str:
        reader = PdfReader(file_path)
        full_text = []
        
        for page in reader.pages:
            text = page.extract_text()
            if text and text.strip():
                full_text.append(text)
        
        return "\n".join(full_text)



class NLTKTextChunker:    
    def __init__(self, window_size: int = 3, overlap: int = 1):
        self.window_size = window_size
        self.overlap = overlap
    
    def chunk_text(self, text: str) -> List[Dict[str, any]]:
        sentences = sent_tokenize(text)
        
        chunks = []
        for i in range(0, len(sentences), self.window_size - self.overlap):
            window = sentences[i:i + self.window_size]
            
            if len(window) == 0:
                continue
            chunk_text = " ".join(window)
            
            chunk_data = {
                'text': chunk_text,
                'start_sentence': i,
                'end_sentence': i + len(window),
                'num_sentences': len(window),
                'chunk_id': len(chunks)
            }
            
            chunks.append(chunk_data)
            
            if i + self.window_size >= len(sentences):
                break
        
        return chunks


class BERTEmbedder:
    
    def __init__(self, model_name: str = 'bert-base-uncased'):
        print(f"Loading BERT model: {model_name}")
        self.tokenizer = BertTokenizer.from_pretrained(model_name)
        self.model = BertModel.from_pretrained(model_name)
        self.model.eval() 
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model.to(self.device)
        print(f"Using device: {self.device}")
    
    def get_embedding(self, text: str) -> np.ndarray:
        inputs = self.tokenizer(
            text,
            return_tensors='pt',
            truncation=True,
            max_length=512,
            padding=True
        )
        

        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        

        with torch.no_grad():
            outputs = self.model(**inputs)
        
        cls_embedding = outputs.last_hidden_state[:, 0, :].cpu().numpy()
        
        return cls_embedding[0]
    
    def batch_embed(self, texts: List[str], batch_size: int = 8) -> List[np.ndarray]:
        embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            print(f"Processing batch {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1}")
            
            for text in batch:
                embedding = self.get_embedding(text)
                embeddings.append(embedding)
        
        return embeddings


class ChromaVectorStore:
    def __init__(self, collection_name: str = "postgres_docs", persist_directory: str = "./chroma_db"):
        self.persist_directory = persist_directory
        
        self.client = chromadb.Client(Settings(
            persist_directory=persist_directory,
            anonymized_telemetry=False
        ))
        
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"} 
        )
        
        print(f"Vector store initialized with collection: {collection_name}")
    
    def add_documents(self, chunks: List[Dict], embeddings: List[np.ndarray]):
     
        ids = [f"chunk_{chunk['chunk_id']}" for chunk in chunks]
        documents = [chunk['text'] for chunk in chunks]
        metadatas = [
            {
                'start_sentence': chunk['start_sentence'],
                'end_sentence': chunk['end_sentence'],
                'num_sentences': chunk['num_sentences']
            }
            for chunk in chunks
        ]
        
        embeddings_list = [emb.tolist() for emb in embeddings]
        
        self.collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings_list,
            metadatas=metadatas
        )
        
        print(f"Added {len(chunks)} chunks to vector store")
    
    def search(self, query_embedding: np.ndarray, n_results: int = 5) -> Dict:
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=n_results
        )
        
        return results


class RAGSystem:
   
    def __init__(self, window_size: int = 3, overlap: int = 1):
        self.doc_processor = DocumentProcessor()
        self.chunker = NLTKTextChunker(window_size=window_size, overlap=overlap)
        self.embedder = BERTEmbedder()
        self.vector_store = ChromaVectorStore()
        
        self.system_prompt = """You are a helpful assistant that answers questions based ONLY on the provided context.

CRITICAL INSTRUCTIONS:
1. Use ONLY the information from the context provided below
2. If the context does not contain information to answer the question, respond with: "I cannot find information about that in the provided documentation."
3. Do NOT use your general knowledge or make assumptions
4. Do NOT hallucinate or invent information
5. If you're unsure, admit it rather than guessing

Context:
{context}

Question: {question}

Answer:"""
    
    def ingest_document(self, file_path: str):
        print("\n" + "="*60)
        print("STARTING DOCUMENT INGESTION")
        print("="*60)
        

        print("\n[1/4] Loading document...")
        text = self.doc_processor.load_pdf_document(file_path)
        print(f"Loaded document with {len(text)} characters")
        
        print("\n[2/4] Chunking text with NLTK...")
        chunks = self.chunker.chunk_text(text)
        print(f"Created {len(chunks)} chunks")
        
        print("\n[3/4] Generating BERT embeddings...")
        texts = [chunk['text'] for chunk in chunks]
        embeddings = self.embedder.batch_embed(texts)
        print(f"Generated {len(embeddings)} embeddings")
        
        print("\n[4/4] Storing in ChromaDB...")
        self.vector_store.add_documents(chunks, embeddings)
        
        print("\n" + "="*60)
        print("INGESTION COMPLETE")
        print("="*60)
    
    def query(self, question: str, n_results: int = 3) -> Tuple[str, List[Dict]]:
        print(f"\n[QUERY] {question}")
        
        # Generate query embedding
        query_embedding = self.embedder.get_embedding(question)
    
        # Retrieve relevant chunks
        results = self.vector_store.search(query_embedding, n_results=n_results)
        
        # Format context
        contexts = []
        if results['documents'] and len(results['documents'][0]) > 0:
            for i, (doc, metadata, distance) in enumerate(zip(
                results['documents'][0],
                results['metadatas'][0],
                results['distances'][0]
            )):
                contexts.append({
                    'text': doc,
                    'metadata': metadata,
                    'similarity': 1 - distance 
                })
                print(f"\n[Context {i+1}] Similarity: {1-distance:.3f}")
                print(f"Text: {doc[:200]}...")
        
        context_text = "\n\n".join([f"[Context {i+1}]: {ctx['text']}" 
                                     for i, ctx in enumerate(contexts)])
        
        prompt = self.system_prompt.format(context=context_text, question=question)
        tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL)
        inputs = tokenizer(prompt, return_tensors="pt").to(llm.device)
        outputs = llm.generate(
            **inputs,
            max_new_tokens=200,
            temperature=0.7
        )

        print(tokenizer.decode(outputs[0], skip_special_tokens=True))
        


if __name__ == "__main__":
    rag = RAGSystem(window_size=3, overlap=1)
    
    print("\nTo ingest a document, use:")
    rag.ingest_document("Week1/Task3/docs.pdf")
    while(True):
        string = input()
        if string.upper() != "BYE":
            rag.query(input())
        else:
            break
