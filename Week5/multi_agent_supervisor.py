"""
Multi-Tool Agent - Using AWS Bedrock
Supports Claude, Llama, Titan, and other Bedrock models
"""

from typing import List, Dict
import os


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
from typing import TypedDict
from langgraph.graph import START, StateGraph, END

flag_it = False
flag_fin = False
agent_it = ""
agent_fin = ""
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)
    nltk.download('punkt_tab', quiet=True)

class AgentState(TypedDict):
    user_query: str
    answer: str

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
                 region_name: str = "us-east-1",
                 system_prompt:str = "You are a helpful AI assitant."):
    
        # Check AWS credentials
        if not (os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY')):
            return
        try:
            self.llm = ChatBedrockConverse(
    model=model_id, 
    temperature=0.1,
    max_tokens=2000
)
            
            # Test connection
            self.llm.invoke("test")
        except Exception as e:
            print(f"Bedrock error: {e}")
            raise
        
        # Components
        self.rag_system = RAGSystem()
        
        self.search = DuckDuckGoSearchAPIWrapper()

        
        # Tools
        self.tools = self._create_tools()
        
        # Agent
        self.agent = self._create_agent(system_prompt)
    
    def _create_tools(self) -> List:
        rag = self.rag_system
        search = self.search
        
        
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
        
        return [rag_query, web_search]
    
    def _create_agent(self, system_prompt):
        """ Agent that Handles all IT-related queries"""
        
        prompt = system_prompt
        
        # Create agent with Bedrock (supports bind_tools!)
        agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=prompt
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
            # print("="*60)
            # print(answer)
            return answer
        except Exception as e:
            error = f" {e}"
            print(error)
            return error





def it_agent(state: AgentState):
    """ Agent that Handles all IT (Income Tax) -related queries"""

    default_model = "anthropic.claude-3-sonnet-20240229-v1:0"
    model_id = default_model
    
    region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
    prompt = """You are a helpful AI assistant with access to three tools:

1. rag_query - Search through stored PDF documents
2. web_search - Search the internet for current information

TOOL SELECTION GUIDE:

Use rag_query when:
- User asks about IT (Income tax) related  queries and if the document has sufficient context that answers the question , provide the answer to the user. 
- If the context is insufficient use the web serarch tool.

Use web_search when:
- Need current information, news, or trends
- User asks for "latest..." or "current..." or "recent..."
- When RAG has no answer
- To supplement RAG with up-to-date info

You can use MULTIPLE tools for one question if needed!
Always think step-by-step and choose the most appropriate tool(s)."""
    global flag_it
    global agent_it
    try:
        if not flag_it:
            flag_it = True
            agent_it = MultiToolAgent(model_id=model_id, region_name=region , system_prompt= prompt)
            pdf = "Week5/IT.pdf"
            if pdf:
                print(agent_it.ingest_pdf(pdf))
    except Exception as e:
        print(f"\n Failed to initialize: {e}")
        return
    
    try:
            print("--- IT Agent thinking... ---")
            q = state["user_query"]
            
            if not q:
               return
            
            return agent_it.query(q)

    except Exception as e:
            print(f"\n {e}")



def finance_agent(state: AgentState):
    """ Agent that Handles all Fiance-related queries"""

    
    default_model = "anthropic.claude-3-sonnet-20240229-v1:0"
    model_id = default_model
    
    region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
    prompt = """You are a helpful AI assistant with access to three tools:

1. rag_query - Search through stored PDF documents
2. web_search - Search the internet for current information

TOOL SELECTION GUIDE:

Use rag_query when:
- User asks about Finance queries and if the document has sufficient context that answers the question , provide the answer to the user. 
- If the context is insufficient use the web serarch tool.

Use web_search when:
- Need current information, news, or trends
- User asks for "latest..." or "current..." or "recent..."
- When RAG has no answer
- To supplement RAG with up-to-date info

You can use MULTIPLE tools for one question if needed!
Always think step-by-step and choose the most appropriate tool(s)."""
    global flag_fin
    global agent_fin
    try:
        if not flag_fin:
            flag_fin = True
            agent_fin = MultiToolAgent(model_id=model_id, region_name=region , system_prompt= prompt)
            pdf = "Week5/finance.pdf"
            if pdf:
                print(agent_fin.ingest_pdf(pdf))
    except Exception as e:
        print(f"\n Failed to initialize: {e}")
        return

    try:
            print("--- Fianance Agent thinking... ---")
            q = state["user_query"]
            
            if not q:
               return
            
            return agent_fin.query(q)

    except Exception as e:
            print(f"\n {e}")



agent_docs = {
    "it_agent": it_agent.__doc__,
    "finance_agent": finance_agent.__doc__
}
def routing_logic(state: AgentState):
    """
    Uses the LLM to choose between 'it_agent' and 'finance_agent'
    based on the intent of the user query and the agents' docstrings.
"""
    prompt = f"""
    You are a router agent. Your task is to choose the best agent for the job.
    Here is the user query: {state['user_query']}

    You can choose from the following agents:
    - it_agent: {agent_docs['it_agent']}
    - finance_agent: {agent_docs['finance_agent']}

    Which agent should handle this query? Respond with just the agent name.
    """
    
    default_model = "anthropic.claude-3-sonnet-20240229-v1:0"
    model_id = default_model
    
    llm = ChatBedrockConverse(
    model=model_id, 
    temperature=0.1,
    max_tokens=2000
)
    response = llm.invoke(prompt)
    decision = response.content.strip().lower()
    return "it_agent" if "it" in decision else "finance_agent"
def router_agent(state: AgentState) -> str:
    """
    Captures a user query from the command line and updates the state.

    This function acts as an input node in the LangGraph workflow. It prompts the user
    to enter a query via the console, then stores that input in the shared state under
    the 'user_query' key, which will be used to route to the appropriate agents.

    Args:
        state (AgentState): The current state dictionary (can be empty or partially filled).

    Returns:
        dict: Updated state containing the user's query.
    """
    print("--- Routeing agent ---")
    state['user_query'] = input("Q: ")
    return state

def main():
    os.environ['AWS_ACCESS_KEY_ID'] = 'AKIA47GB73VYWPKDGL2F'
    os.environ['AWS_SECRET_ACCESS_KEY'] = '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'
    os.environ['AWS_DEFAULT_REGION'] = "us-east-1"
    workflow = StateGraph(AgentState)
    workflow.add_node("routing_agent", router_agent) 
    workflow.add_node("it_agent", it_agent)
    workflow.add_node("finance_agent", finance_agent) 

    workflow.add_edge(START, "routing_agent")
    workflow.add_conditional_edges("routing_agent", routing_logic)
    workflow.add_edge("it_agent", END)
    workflow.add_edge("finance_agent", END)

    app = workflow.compile()
    while True:
        try:
            result = app.invoke({})["answer"]
            print(result)
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\n {e}")

if __name__ == "__main__":
    main()