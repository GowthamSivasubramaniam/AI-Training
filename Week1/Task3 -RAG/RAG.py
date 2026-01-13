from transformers import AutoTokenizer, AutoModelForCausalLM
from sentence_transformers import SentenceTransformer
import faiss
import torch


LLM_MODEL = "mistralai/Mistral-7B-Instruct-v0.2"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL)
llm = AutoModelForCausalLM.from_pretrained(
    LLM_MODEL,
    device_map="auto",
    torch_dtype=torch.float16
)

embedder = SentenceTransformer(EMBED_MODEL)


docs = [
    "The Eiffel Tower is a wrought-iron tower in Paris, France.",
    "It was built in 1889 for the World's Fair.",
    "If destroyed, France would lose a major cultural landmark."
]


doc_embeddings = embedder.encode(docs, convert_to_numpy=True)

index = faiss.IndexFlatL2(doc_embeddings.shape[1])
index.add(doc_embeddings)

# --------------------
# RAG function
# --------------------
def rag_answer(query, top_k=2):
    query_embedding = embedder.encode([query], convert_to_numpy=True)
    _, indices = index.search(query_embedding, top_k)

    context = "\n".join([docs[i] for i in indices[0]])

    prompt = f"""Use the context below to answer the question.

Context:
{context}

Question:
{query}

Answer:"""

    inputs = tokenizer(prompt, return_tensors="pt").to(llm.device)
    outputs = llm.generate(
        **inputs,
        max_new_tokens=200,
        temperature=0.7
    )

    return tokenizer.decode(outputs[0], skip_special_tokens=True)

# --------------------
# Ask question
# --------------------
print(rag_answer("What is the Eiffel Tower and what happens if it is destroyed?"))
