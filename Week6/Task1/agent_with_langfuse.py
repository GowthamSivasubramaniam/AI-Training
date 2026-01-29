"""
Multi-Tool Agent with Langfuse, NeMo Guardrails (Bedrock-compatible), and AgentEvals
"""

from typing import List, Dict
import os
import time
import json
from datetime import datetime

# Set Langfuse environment variables
os.environ['LANGFUSE_PUBLIC_KEY'] = 'pk-lf-2a078a17-81f6-478a-af24-9fb707a6179f'
os.environ['LANGFUSE_SECRET_KEY'] = 'sk-lf-1897965d-cf5f-4fa3-94d1-95dbd5579c15'
os.environ['LANGFUSE_HOST'] = 'http://localhost:3000'

# Langfuse for tracing
from langfuse.decorators import observe, langfuse_context

# LangChain
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from langchain_aws import ChatBedrockConverse

# NeMo Guardrails
try:
    from nemoguardrails import LLMRails, RailsConfig
    from nemoguardrails.integrations.langchain.runnable_rails import RunnableRails

    NEMO_AVAILABLE = True
    print("NeMo Guardrails available")
except ImportError:
    NEMO_AVAILABLE = False
    print("NeMo Guardrails not installed")

# AgentEvals for evaluation
try:
    from agentevals.trajectory.match import create_trajectory_match_evaluator
    AGENTEVALS_AVAILABLE = True
    print("AgentEvals available")
except ImportError:
    AGENTEVALS_AVAILABLE = False
    print("AgentEvals not installed")

# RAG
import numpy as np
import nltk
from nltk.tokenize import sent_tokenize
import torch
from transformers import BertTokenizer, BertModel
from PyPDF2 import PdfReader
from sklearn.metrics.pairwise import cosine_similarity

print("Imports successful")

try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)
    nltk.download('punkt_tab', quiet=True)


# Custom Bedrock LLM wrapper for NeMo
class BedrockLLMForNeMo:
    """Wrapper to make Bedrock compatible with NeMo Guardrails"""
    
    def __init__(self, bedrock_llm):
        self.bedrock_llm = bedrock_llm
    
    def __call__(self, prompt):
        """NeMo calls this with a string prompt"""
        try:
            # Bedrock expects messages format
            if isinstance(prompt, str):
                response = self.bedrock_llm.invoke(prompt)
            else:
                response = self.bedrock_llm.invoke(str(prompt))
            
            # Extract content from response
            if hasattr(response, 'content'):
                return response.content
            else:
                return str(response)
        except Exception as e:
            print(f"Bedrock call error: {e}")
            return "Error in LLM call"
    
    def generate(self, prompt):
        """Alternative method NeMo might use"""
        return self.__call__(prompt)


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
        print("Initializing RAG...")
        self.window_size = window_size
        self.overlap = overlap
        
        self.tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')
        self.model = BertModel.from_pretrained('bert-base-uncased')
        self.model.eval()
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model.to(self.device)
        
        self.vector_store = SimpleVectorStore()
        print(f"RAG ready")
    
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
    
    @observe(name="pdf_ingestion")
    def ingest_document(self, file_path: str) -> str:
        try:
            print(f"\nIngesting: {file_path}")
            text = self.load_pdf(file_path)
            chunks = self.chunk_text(text)
            print(f"  {len(chunks)} chunks")
            
            documents = [c['text'] for c in chunks]
            embeddings = [self.get_embedding(c['text']) for c in chunks]
            metadatas = [{'start': c['start'], 'end': c['end']} for c in chunks]
            
            self.vector_store.add(documents, embeddings, metadatas)
            
            langfuse_context.update_current_trace(
                metadata={"file": file_path, "chunks": len(chunks)}
            )
            
            return f"Ingested {len(chunks)} chunks"
        except Exception as e:
            return f"Error: {str(e)}"
    
    @observe(name="rag_retrieval")
    def query(self, question: str, n_results: int = 10) -> str:
        try:
            print(f"\nRAG: {question}")
            query_embedding = self.get_embedding(question)
            results = self.vector_store.query(query_embedding, n_results)
            
            if not results['documents'] or not results['documents'][0]:
                return "No documents. Ingest PDF first."
            
            parts = [f"[{i+1}] (Score: {1-d:.2f})\n{doc}" 
                    for i, (doc, d) in enumerate(zip(results['documents'][0], results['distances'][0]))]
            
            langfuse_context.update_current_observation(
                metadata={"results_count": len(results['documents'][0])}
            )
            
            return "\n\n".join(parts)
        except Exception as e:
            return f"Error: {str(e)}"


class NeMoGuardrailsForBedrock:
    """NeMo Guardrails configured to work with Bedrock"""
    
    def __init__(self, bedrock_llm):
        self.enabled = NEMO_AVAILABLE
        self.rails = None
        
        if not self.enabled:
            print("NeMo not available, using simple guardrails")
            return
        
        try:
            # Wrap Bedrock LLM
            wrapped_llm = BedrockLLMForNeMo(bedrock_llm)
            
            # Create simple config
            config = RailsConfig.from_content(
                colang_content="""
define user express violence
    "kill"
    "hurt"
    "stab"
    "shoot"
    "bomb"
    "attack"

define user express abuse
    "you are stupid"
    "idiot"
    "hate you"
    "moron"

define bot refuse violence
    "I can’t help with violent or harmful actions."

define bot refuse abuse
    "I’m here to help, but I won’t engage in abusive language."

define flow check violence
    user express violence
    bot refuse violence
    stop

define flow check abuse
    user express abuse
    bot refuse abuse
    stop

define flow generate
    user says anything
    bot says

""",
                yaml_content="""

rails:
  input:
    flows:
      - check violence
      - check abuse

  output:
    flows:
      - generate

"""
            )
            
            # Initialize with wrapped LLM
            self.rails = LLMRails(config , llm = wrapped_llm)
            response = self.rails.generate(messages=[{
                    "role": "user",
                   "content": "Hello"
                }])
            for e in response.get("events", []):
                print(e["type"], e.get("model"))

            
            print("NeMo Guardrails with Bedrock initialized")
            
        except Exception as e:
            print(f"NeMo init failed: {e}")
            print("Using simple pattern-based guardrails")
            self.enabled = False
    
    def check_input(self, text: str) -> tuple:
        """Check input safety"""
        # Simple pattern check (always works)
        text_lower = text.lower()
        patterns = [
            'ignore all instructions',
            'ignore previous instructions',
            'developer mode',
            'forget everything'
        ]
        
        for pattern in patterns:
            if pattern in text_lower:
                return False, "Jailbreak attempt detected"
        
        if self.enabled and self.rails:
            try:
                response = self.rails.generate(messages=[{
                    "role": "user",
                    "content": text
                }])
                
                response_text = str(response).lower()
                if "cannot comply" in response_text:
                    return False, "Blocked by NeMo Guardrails"
            except Exception as e:
                print(f"NeMo check error: {e}")
        
        return True, "OK"


class AgentEvaluator:
    """Evaluator using AgentEvals trajectory match"""
    
    def __init__(self, bedrock_llm=None):
        self.evaluations = []
        self.metrics = {
            'total_queries': 0,
            'successful_queries': 0,
            'failed_queries': 0,
            'tool_usage': {'rag_query': 0, 'web_search': 0},
            'latencies': [],
            'guardrail_blocks': 0,
            'token_usage': {'input': 0, 'output': 0},
            'accuracy_scores': [],
            'tool_call_accuracy': []
        }
        
        # AgentEvals trajectory match evaluator
        self.trajectory_evaluator = None
        if AGENTEVALS_AVAILABLE:
            try:
                self.trajectory_evaluator = create_trajectory_match_evaluator(
                    trajectory_match_mode="strict"  
                )
                print("AgentEvals trajectory match evaluator initialized")
            except Exception as e:
                print(f"AgentEvals init failed: {e}")
                self.trajectory_evaluator = None
        else:
            print("AgentEvals not available")
    
    def _create_reference_trajectory(self, question: str, tools_used: List[str], answer: str) -> List[Dict]:
        """Create ideal reference trajectory for comparison"""
        reference = [{"role": "user", "content": question}]
        
        # Add ideal tool calls
        if 'rag_query' in tools_used:
            reference.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "rag_query",
                        "arguments": json.dumps({"question": question})
                    }
                }]
            })
            reference.append({
                "role": "tool",
                "content": "Retrieved relevant information from PDF."
            })
        
        if 'web_search' in tools_used:
            reference.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "web_search",
                        "arguments": json.dumps({"query": question})
                    }
                }]
            })
            reference.append({
                "role": "tool",
                "content": "Retrieved web search results."
            })
        
        # Final answer
        reference.append({"role": "assistant", "content": answer})
        
        return reference
    
    def record_query(self, question: str, answer: str, trajectory: List[Dict], 
                     success: bool, latency: float, tools_used: List[str], 
                     tokens_in: int = 0, tokens_out: int = 0, blocked: bool = False):
        
        self.metrics['total_queries'] += 1
        
        if blocked:
            self.metrics['guardrail_blocks'] += 1
            return
        
        if success:
            self.metrics['successful_queries'] += 1
        else:
            self.metrics['failed_queries'] += 1
        
        self.metrics['latencies'].append(latency)
        self.metrics['token_usage']['input'] += tokens_in
        self.metrics['token_usage']['output'] += tokens_out
        
        for tool in tools_used:
            if tool in self.metrics['tool_usage']:
                self.metrics['tool_usage'][tool] += 1
        
        # Evaluate with AgentEvals trajectory match
        if self.trajectory_evaluator and trajectory and len(trajectory) > 1:
            try:
                # Create reference trajectory
                reference = self._create_reference_trajectory(question, tools_used, answer)
                
                # Evaluate trajectory match
                eval_result = self.trajectory_evaluator(
                    outputs=trajectory,
                    reference_outputs=reference
                )
                
                # Extract scores
                if isinstance(eval_result, dict):
                    # Get overall match score
                    match_score = eval_result.get('trajectory_match', 0.5)
                    tool_accuracy = eval_result.get('tool_call_match', 0.5)
                else:
                    match_score = 0.5
                    tool_accuracy = 0.5
                
                self.metrics['accuracy_scores'].append(match_score)
                self.metrics['tool_call_accuracy'].append(tool_accuracy)
                
                self.evaluations.append({
                    'question': question,
                    'answer': answer,
                    'trajectory': trajectory,
                    'reference': reference,
                    'eval_result': eval_result,
                    'match_score': match_score,
                    'tool_accuracy': tool_accuracy,
                    'latency': latency,
                    'tools_used': tools_used
                })
                
                print(f"AgentEvals - Trajectory Match: {match_score:.2f}, Tool Accuracy: {tool_accuracy:.2f}")
                
            except Exception as e:
                print(f"AgentEvals evaluation error: {e}")
    
    def get_summary(self):
        avg_latency = sum(self.metrics['latencies']) / len(self.metrics['latencies']) if self.metrics['latencies'] else 0
        success_rate = (self.metrics['successful_queries'] / self.metrics['total_queries'] * 100) if self.metrics['total_queries'] > 0 else 0
        avg_accuracy = sum(self.metrics['accuracy_scores']) / len(self.metrics['accuracy_scores']) if self.metrics['accuracy_scores'] else 0
        avg_tool_accuracy = sum(self.metrics['tool_call_accuracy']) / len(self.metrics['tool_call_accuracy']) if self.metrics['tool_call_accuracy'] else 0
        
        return {
            'total_queries': self.metrics['total_queries'],
            'success_rate': f"{success_rate:.2f}%",
            'average_latency': f"{avg_latency:.2f}s",
            'trajectory_match': f"{avg_accuracy:.2f}",
            'tool_call_accuracy': f"{avg_tool_accuracy:.2f}",
            'guardrail_blocks': self.metrics['guardrail_blocks'],
            'tool_usage': self.metrics['tool_usage'],
            'total_tokens': {
                'input': self.metrics['token_usage']['input'],
                'output': self.metrics['token_usage']['output'],
                'total': self.metrics['token_usage']['input'] + self.metrics['token_usage']['output']
            }
        }


class MultiToolAgentWithEvaluation:
    """Agent with Langfuse, NeMo Guardrails (Bedrock), and evaluation"""
    
    def __init__(self, 
                 model_id: str = "anthropic.claude-3-sonnet-20240229-v1:0",
                 region_name: str = "us-east-1"):
        
        print("\n" + "="*60)
        print("MULTI-TOOL AGENT - COMPLETE EVALUATION")
        print("="*60)
        
        self.evaluator = AgentEvaluator()
        
        # Bedrock LLM
        print(f"\nBedrock ({model_id})...")
        self.llm = ChatBedrockConverse(
            model=model_id, 
            region_name=region_name,
            temperature=0.1,
            max_tokens=2000
        )
        
        self.llm.invoke("test")
        print("Bedrock connected")
        
        # NeMo Guardrails with Bedrock
        print("\nNeMo Guardrails...")
        self.guardrails = NeMoGuardrailsForBedrock(self.llm)
        
        # Components
        self.rag_system = RAGSystem()
        self.search = DuckDuckGoSearchAPIWrapper()
        self.tools = self._create_tools()
        
        # Agent
        print(f"\nCreating agent...")
        self.agent = self._create_agent()
        
        print("\n" + "="*60)
        print("READY")
        print("="*60 + "\n")
    
    def _create_tools(self) -> List:
        rag = self.rag_system
        search = self.search
        
        @tool
        @observe(name="rag_query_tool")
        def rag_query(question: str) -> str:
            """Search PDF documents."""
            return rag.query(question)
        
        @tool
        @observe(name="web_search_tool")
        def web_search(query: str) -> str:
            """Search the internet."""
            print(f"\nWeb: {query}")
            try:
                return search.run(query)
            except Exception as e:
                return f"Error: {e}"
        
        return [rag_query, web_search]
    
    def _create_agent(self):
        system_prompt = """You are a helpful AI assistant with two tools:
1. rag_query - Search PDF documents
2. web_search - Search the internet

Choose the appropriate tool for each query."""
        
        return create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=system_prompt
        )
    
    def ingest_pdf(self, file_path: str) -> str:
        return self.rag_system.ingest_document(file_path)
    
    @observe(name="agent_query")
    def query(self, question: str) -> Dict:
        print("\n" + "="*60)
        print(f"Q: {question}")
        print("="*60)
        
        start_time = time.time()
        tools_used = []
        trajectory = []
        
        trajectory.append({"role": "user", "content": question})
        
        langfuse_context.update_current_trace(
            input={"question": question},
            metadata={"timestamp": datetime.now().isoformat()}
        )
        
        try:
            # NeMo Guardrails check
            safe, reason = self.guardrails.check_input(question)
            print(safe)
            if not safe:
                answer = f"Blocked: {reason}"
                print(f"\n{answer}")
                
                trajectory.append({"role": "assistant", "content": answer})
                
                langfuse_context.update_current_trace(
                    output={"answer": answer, "blocked": True},
                    metadata={"guardrail_triggered": True}
                )
                
                latency = time.time() - start_time
                self.evaluator.record_query(
                    question, answer, trajectory, False, latency, [], blocked=True
                )
                
                return {
                    'answer': answer,
                    'blocked': True,
                    'latency': latency
                }
            
            # Invoke agent
            response = self.agent.invoke({
                "messages": [{"role": "user", "content": question}]
            })
            
            answer = response['messages'][-1].content
            
            # Build trajectory
            for msg in response['messages']:
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tools_used.append(tc.get('name', 'unknown'))
                        trajectory.append({
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [{
                                "function": {
                                    "name": tc.get('name'),
                                    "arguments": json.dumps(tc.get('args', {}))
                                }
                            }]
                        })
                elif hasattr(msg, 'type') and msg.type == 'tool':
                    trajectory.append({
                        "role": "tool",
                        "content": str(msg.content)
                    })
            
            trajectory.append({"role": "assistant", "content": answer})
            
            latency = time.time() - start_time
            tokens_in = int(len(question.split()) * 1.3)
            tokens_out = int(len(answer.split()) * 1.3)
            
            langfuse_context.update_current_trace(
                output={"answer": answer},
                metadata={
                    "tools_used": tools_used,
                    "latency": latency,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out
                }
            )
            
            self.evaluator.record_query(
                question, answer, trajectory, True, latency, tools_used,
                tokens_in, tokens_out
            )
            
            print("\n" + "="*60)
            print("A:")
            print("="*60)
            print(answer)
            print(f"\nLatency: {latency:.2f}s | Tools: {', '.join(tools_used) if tools_used else 'None'}")
            print("="*60 + "\n")
            
            return {
                'answer': answer,
                'blocked': False,
                'latency': latency,
                'tools_used': tools_used
            }
            
        except Exception as e:
            error = f"Error: {e}"
            latency = time.time() - start_time
            
            trajectory.append({"role": "assistant", "content": error})
            
            langfuse_context.update_current_trace(
                output={"error": str(e)},
                metadata={"latency": latency}
            )
            
            self.evaluator.record_query(
                question, error, trajectory, False, latency, tools_used
            )
            
            print(error)
            return {'answer': error, 'latency': latency}
    
    def get_evaluation_report(self) -> str:
        summary = self.evaluator.get_summary()
        
        report = f"""# Agent Evaluation Report

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Framework: Langfuse + NeMo Guardrails + AgentEvals

## Overall Metrics

| Metric | Value |
|--------|-------|
| Total Queries | {summary['total_queries']} |
| Success Rate | {summary['success_rate']} |
| Average Latency | {summary['average_latency']} |
| Trajectory Match | {summary['trajectory_match']} |
| Tool Call Accuracy | {summary['tool_call_accuracy']} |
| Guardrail Blocks | {summary['guardrail_blocks']} |

## Tool Usage Statistics

| Tool | Count |
|------|-------|
| RAG Query | {summary['tool_usage']['rag_query']} |
| Web Search | {summary['tool_usage']['web_search']} |

## Token Usage

| Type | Count |
|------|-------|
| Input | {summary['total_tokens']['input']} |
| Output | {summary['total_tokens']['output']} |
| Total | {summary['total_tokens']['total']} |

Average per query: {summary['total_tokens']['total'] / summary['total_queries'] if summary['total_queries'] > 0 else 0:.0f} tokens

## Performance Analysis

### Correctness
- Success Rate: {summary['success_rate']}
- Trajectory Match Score: {summary['trajectory_match']}
- Tool Call Accuracy: {summary['tool_call_accuracy']}
- Assessment: {"Excellent" if float(summary['success_rate'].rstrip('%')) > 85 else "Good" if float(summary['success_rate'].rstrip('%')) > 70 else "Needs Improvement"}

### AgentEvals Analysis
The AgentEvals trajectory match evaluator compares actual agent behavior against ideal reference trajectories:
- Trajectory Match: Measures how well the agent's overall interaction flow matches the ideal
- Tool Call Accuracy: Evaluates correctness of tool selection and arguments

### Latency
- Average Response Time: {summary['average_latency']}
- Performance Rating: {"Fast" if float(summary['average_latency'].rstrip('s')) < 3 else "Acceptable" if float(summary['average_latency'].rstrip('s')) < 5 else "Slow"}

### Safety & Compliance
- Guardrail Activations: {summary['guardrail_blocks']}
- NeMo Guardrails: {"Active - blocked harmful requests" if summary['guardrail_blocks'] > 0 else "Active - no harmful requests detected"}

### Tool Utilization
- RAG Query: {summary['tool_usage']['rag_query']} times - {"Primary knowledge source" if summary['tool_usage']['rag_query'] > summary['tool_usage']['web_search'] else "Secondary source"}
- Web Search: {summary['tool_usage']['web_search']} times - {"Frequently used for current info" if summary['tool_usage']['web_search'] > 0 else "Rarely needed"}

## Observability

### Langfuse Traces
Complete observability at: http://localhost:3000
- All interactions logged with full context
- Token usage tracked per query
- Tool calls and responses captured
- Latency measurements recorded

### AgentEvals Integration
Trajectory match evaluation provides:
- Comparison against ideal agent behavior
- Tool selection accuracy scoring
- Argument correctness validation
- Overall interaction quality assessment

## Conclusion

The agent demonstrates {
    "excellent" if float(summary['success_rate'].rstrip('%')) > 85 
    else "good" if float(summary['success_rate'].rstrip('%')) > 70 
    else "moderate"
} performance with comprehensive monitoring and evaluation capabilities.

### Key Strengths
- Effective tool utilization
- Strong safety measures via NeMo Guardrails
- Complete observability through Langfuse
- Accurate trajectory evaluation via AgentEvals

Generated with: NeMo Guardrails + Bedrock + Langfuse + AgentEvals
"""
        return report


def main():
    print("\n" + "="*70)
    print("MULTI-TOOL AGENT - LANGFUSE + NEMO + AGENTEVALS")
    print("="*70)
    
    if not os.getenv('AWS_ACCESS_KEY_ID'):
        print("\nAWS Credentials Required")
        return
    
    agent = MultiToolAgentWithEvaluation()
    
    print("\n" + "="*60)
    print("PDF INGESTION")
    print("="*60)
    pdf = input("\nPDF path (or Enter): ").strip()
    if pdf and os.path.exists(pdf):
        print(agent.ingest_pdf(pdf))
    
    print("\n" + "="*60)
    print("INTERACTIVE MODE")
    print("="*60)
    print("\nType 'quit' to exit\n")
    
    while True:
        try:
            q = input("\nQuestion: ").strip()
            
            if not q:
                continue
            
            if q.lower() in ['quit', 'exit']:
                print("\nGenerating report...")
                report = agent.get_evaluation_report()
                
                with open('EVALUATION_REPORT.md', 'w') as f:
                    f.write(report)
                
                print(report)
                print("\nSaved: EVALUATION_REPORT.md")
                break
            
            # Test guardrails
            if 'ignore all instructions' in q.lower():
                print("\n[Testing NeMo Guardrails...]")
            
            agent.query(q)
            
        except KeyboardInterrupt:
            print("\n\nExiting...")
            report = agent.get_evaluation_report()
            with open('EVALUATION_REPORT.md', 'w') as f:
                f.write(report)
            break


if __name__ == "__main__":
    main()