"""
Multi-Tool Agent - Using AWS Bedrock
Supports Claude, Llama, Titan, and other Bedrock models
"""

import asyncio
from typing import List, Dict
from pathlib import Path
import sys
import os

# Direct import of your MCP server
sys.path.insert(0, str(Path(__file__).parent))
from google_docs_mcp import GoogleDocsReadServer

# Imports for Bedrock
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from langchain_aws import ChatBedrockConverse

# RAG imports
import numpy as np
import nltk
from nltk.tokenize import sent_tokenize
import torch
from transformers import BertTokenizer, BertModel
from PyPDF2 import PdfReader
from sklearn.metrics.pairwise import cosine_similarity

try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)
    nltk.download('punkt_tab', quiet=True)


class OptimizedMCPClient:
    def __init__(self):
        print("🔌 MCP Client...")
        self.server = GoogleDocsReadServer()
        self.server.authenticate()
        print(" MCP ready")
    
    def read_document(self, document_id: str) -> str:
        try:
            print(f"📄 Reading: {document_id}")
            async def read():
                result = await self.server.read_document('1jF1E_fM5Rs84JlI02-0AoZ0LksxCiOx3H7ajYHpcel8')
                return result[0].text
            return asyncio.run(read())
        except Exception as e:
            return f" Error: {str(e)}"


class SimpleVectorStore:
    def __init__(self):
        self.documents: List[str] = []
        self.embeddings: List[np.ndarray] = []
        self.metadatas: List[Dict] = []
    
    def add(self, documents: List[str], embeddings: List[np.ndarray], metadatas: List[Dict]):
        self.documents.extend(documents)
        self.embeddings.extend(embeddings)
        self.metadatas.extend(metadatas)
    
    def query(self, query_embedding: np.ndarray, n_results: int = 3) -> Dict:
        if not self.embeddings:
            return {'documents': [[]], 'distances': [[]], 'metadatas': [[]]}
        
        query_embedding = query_embedding.reshape(1, -1)
        embeddings_array = np.array(self.embeddings)
        similarities = cosine_similarity(query_embedding, embeddings_array)[0]
        top_indices = np.argsort(similarities)[::-1][:n_results]
        
        return {
            'documents': [[self.documents[i] for i in top_indices]],
            'distances': [[1 - similarities[i] for i in top_indices]],
            'metadatas': [[self.metadatas[i] for i in top_indices]]
        }


class RAGSystem:
    def __init__(self, window_size: int = 3, overlap: int = 1):
        print("📚 RAG...")
        self.window_size = window_size
        self.overlap = overlap
        
        self.tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')
        self.model = BertModel.from_pretrained('bert-base-uncased')
        self.model.eval()
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model.to(self.device)
        
        self.vector_store = SimpleVectorStore()
        print(f" RAG ready ({self.device})")
    
    def load_pdf(self, file_path: str) -> str:
        reader = PdfReader(file_path)
        return "\n".join([p.extract_text() for p in reader.pages if p.extract_text()])
    
    def chunk_text(self, text: str) -> List[dict]:
        sentences = sent_tokenize(text)
        chunks = []
        for i in range(0, len(sentences), self.window_size - self.overlap):
            window = sentences[i:i + self.window_size]
            if window:
                chunks.append({'text': " ".join(window), 'start': i, 'end': i + len(window), 'id': len(chunks)})
            if i + self.window_size >= len(sentences):
                break
        return chunks
    
    def get_embedding(self, text: str) -> np.ndarray:
        inputs = self.tokenizer(text, return_tensors='pt', truncation=True, max_length=512, padding=True)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self.model(**inputs)
        return outputs.last_hidden_state[:, 0, :].cpu().numpy()[0]
    
    def ingest_document(self, file_path: str) -> str:
        try:
            print(f"\n📥 Ingesting: {file_path}")
            text = self.load_pdf(file_path)
            chunks = self.chunk_text(text)
            print(f"  {len(chunks)} chunks")
            
            documents = [c['text'] for c in chunks]
            embeddings = [self.get_embedding(c['text']) for c in chunks]
            metadatas = [{'start': c['start'], 'end': c['end']} for c in chunks]
            
            self.vector_store.add(documents, embeddings, metadatas)
            return f"Ingested {len(chunks)} chunks"
        except Exception as e:
            return f"Error: {str(e)}"
    
    def query(self, question: str, n_results: int = 10) -> str:
        try:
            print(f"\n🔍 RAG: {question}")
            query_embedding = self.get_embedding(question)
            results = self.vector_store.query(query_embedding, n_results)
            
            if not results['documents'] or not results['documents'][0]:
                return "No docs. Ingest PDF first."
            
            parts = [f"[{i+1}] (Score: {1-d:.2f})\n{doc}" 
                    for i, (doc, d) in enumerate(zip(results['documents'][0], results['distances'][0]))]
            return "\n\n".join(parts)
        except Exception as e:
            return f"Error: {str(e)}"


class MultiToolAgent:
    """Agent using AWS Bedrock - supports bind_tools!"""
    
    def __init__(self, 
                 model_id: str = "anthropic.claude-3-sonnet-20240229-v1:0",
                 region_name: str = "us-east-1"):
        print("\n" + "="*60)
        print("MULTI-TOOL AGENT (AWS Bedrock)")
        print("="*60)
        
        # Check AWS credentials
        if not (os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY')):
            print("\nAWS Credentials Required")
            print("\nSet them:")
            print("  export AWS_ACCESS_KEY_ID='your-access-key'")
            print("  export AWS_SECRET_ACCESS_KEY='your-secret-key'")
            print("  export AWS_DEFAULT_REGION='us-east-1'")
            print("\nOr configure AWS CLI:")
            print("  aws configure")
        
        # Bedrock
        print(f"\nBedrock ({model_id})...")
        try:
            self.llm = ChatBedrockConverse(
    model=model_id, 
    temperature=0.1,
    max_tokens=2000
)
            
            # Test connection
            self.llm.invoke("test")
            print(f"Bedrock connected")
        except Exception as e:
            print(f"Bedrock error: {e}")
            print("\nMake sure:")
            print("  1. AWS credentials are configured")
            print("  2. Bedrock model access is enabled")
            print("  3. Model ID is correct")
            raise
        
        # Components
        self.mcp_client = OptimizedMCPClient()
        self.rag_system = RAGSystem()
        
        print(f"\nWeb...")
        self.search = DuckDuckGoSearchAPIWrapper()
        print(f"Web OK")
        
        # Tools
        self.tools = self._create_tools()
        
        # Agent
        print(f"\nAgent...")
        self.agent = self._create_agent()
        
        print("\n" + "="*60)
        print("READY!")
        print("="*60 + "\n")
    
    def _create_tools(self) -> List:
        mcp = self.mcp_client
        rag = self.rag_system
        search = self.search
        
        @tool
        def google_docs_reader(document_id: str) -> str:
            """Read Google Docs by document ID. Use when user provides doc ID like '1abc123'."""
            try:
                async def read():
                    result = await mcp.server.read_document(document_id)
                    return result[0].text
                return asyncio.run(read())
            except Exception as e:
                return f" {e}"
        
        @tool
        def rag_query(question: str) -> str:
            """Search PDF documents in knowledge base. Use for questions about stored documents."""
            return rag.query(question)
        
        @tool
        def web_search(query: str) -> str:
            """Search the internet for current information. Use for news, trends, recent events."""
            print(f"\nsearchin WEB... - {query}")
            try:
                return search.run(query)
            except Exception as e:
                return f" {e}"
        
        return [google_docs_reader, rag_query, web_search]
    
    def _create_agent(self):
        """Create agent - Bedrock supports bind_tools!"""
        
        system_prompt = """You are a helpful AI assistant with access to three tools:

1. google_docs_reader - Read Google Docs by document ID
2. rag_query - Search through stored PDF documents
3. web_search - Search the internet for current information

TOOL SELECTION GUIDE:

Use google_docs_reader when:
- User asks about insurance policies of presidio , use document id -  1jF1E_fM5Rs84JlI02-0AoZ0LksxCiOx3H7ajYHpcel8
- or any other relevent insurance policy question

Use rag_query when:
- User asks about presidio polices incluing the areas managed by Human resource , dont use web search if the question falls under HR department
- and if used RAG pdf say, "Based on given pdf" and provide the final answer

Use web_search when:
- Need current information, news, or trends
- User asks for "latest..." or "current..." or "recent..."
- When RAG has no answer
- To supplement RAG with up-to-date info

You can use MULTIPLE tools for one question if needed!
Always think step-by-step and choose the most appropriate tool(s)."""
        
        # Create agent with Bedrock (supports bind_tools!)
        agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=system_prompt
        )
        
        return agent
    
    def ingest_pdf(self, file_path: str) -> str:
        return self.rag_system.ingest_document(file_path)
    
    def query(self, question: str) -> str:
        print("\n" + "="*60)
        print(f"Q: {question}")
        print("="*60)
        
        try:
            # Invoke agent
            response = self.agent.invoke({
    "messages": [{"role": "user", "content": question}]
})

            # Then extract the answer from the last message
            messages = response['messages']
            last_message = messages[-1]
            answer = last_message.content
            print("="*60)
            print(answer)
        except Exception as e:
            error = f" {e}"
            print(error)
            return error


def print_available_models():
    """Print available Bedrock models"""
    print("\nPopular Bedrock Models:")
    print("\nClaude (Anthropic):")
    print("  - anthropic.claude-3-sonnet-20240229-v1:0 (recommended)")
    print("  - anthropic.claude-3-haiku-20240307-v1:0 (fast)")
    print("  - anthropic.claude-3-opus-20240229-v1:0 (powerful)")
    print("\nLlama (Meta):")
    print("  - meta.llama3-70b-instruct-v1:0")
    print("  - meta.llama3-8b-instruct-v1:0")
    print("\nTitan (Amazon):")
    print("  - amazon.titan-text-express-v1")
    print("\nMistral:")
    print("  - mistral.mistral-7b-instruct-v0:2")
    print("  - mistral.mixtral-8x7b-instruct-v0:1")


def main():
    print("\n" + "="*70)
    print("MULTI-TOOL AGENT (AWS Bedrock)")
    print("="*70)
    print("\nGoogle Docs | RAG | Web")
    print("="*70)
    
    # Check AWS credentials
    if not (os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY')):
        print("\nAWS Credentials Not Found")
        print("\nOption 1: Set environment variables")
        print("  export AWS_ACCESS_KEY_ID='your-key'")
        print("  export AWS_SECRET_ACCESS_KEY='your-secret'")
        print("  export AWS_DEFAULT_REGION='us-east-1'")
        print("\nOption 2: Configure AWS CLI")
        print("  aws configure")
        print("\nOption 3: Enter them now")
        
        choice = input("\nConfigure now? (y/n): ").strip().lower()
        if choice == 'y':
            os.environ['AWS_ACCESS_KEY_ID'] = input("AWS Access Key ID: ").strip()
            os.environ['AWS_SECRET_ACCESS_KEY'] = input("AWS Secret Access Key: ").strip()
            os.environ['AWS_DEFAULT_REGION'] = input("AWS Region (default: us-east-1): ").strip() or "us-east-1"
        else:
            print("\n Cannot proceed without AWS credentials")
            return
    
    # Show available models
    print_available_models()
    
    # Choose model
    print("\n" + "="*60)
    default_model = "anthropic.claude-3-sonnet-20240229-v1:0"
    model_choice = input(f"\nModel ID (Enter for {default_model}): ").strip()
    model_id = model_choice if model_choice else default_model
    
    region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
    
    try:
        agent = MultiToolAgent(model_id=model_id, region_name=region)
    except Exception as e:
        print(f"\n Failed to initialize: {e}")
        print("\nMake sure:")
        print("  1. AWS credentials are correct")
        print("  2. Bedrock access is enabled in AWS console")
        print("  3. Model is available in your region")
        return
    
    # PDF
    print("\n" + "="*60)
    print("PDF INGESTION")
    print("="*60)
    pdf = input("\nPDF path (Enter to skip): ").strip()
    if pdf:
        print(agent.ingest_pdf(pdf))
    
    # Chat
    print("\n" + "="*60)
    print("INTERACTIVE MODE")
    print("="*60)
    print("\nExamples:")
    print("  'Read document 1abc123'")
    print("  'What's in the PDF about databases?'")
    print("  'Search for latest AI trends'")
    print("\nType 'quit' to exit\n")
    
    while True:
        try:
            q = input("\nQuestion: ").strip()
            
            if not q:
                continue
            
            if q.lower() in ['quit', 'exit', 'bye']:
                print("\nGoodbye!")
                break
            
            agent.query(q)
            
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\n {e}")


if __name__ == "__main__":
    main()