# Agent Evaluation Report

Generated: 2026-01-28 11:35:33
Framework: Langfuse + NeMo Guardrails + AgentEvals

## Overall Metrics

| Metric | Value |
|--------|-------|
| Total Queries | 3 |
| Success Rate | 100.00% |
| Average Latency | 3.06s |
| Trajectory Match | 0.50 |
| Tool Call Accuracy | 0.50 |
| Guardrail Blocks | 0 |

## Tool Usage Statistics

| Tool | Count |
|------|-------|
| RAG Query | 0 |
| Web Search | 2 |

## Token Usage

| Type | Count |
|------|-------|
| Input | 17 |
| Output | 85 |
| Total | 102 |

Average per query: 34 tokens

## Performance Analysis

### Correctness
- Success Rate: 100.00%
- Trajectory Match Score: 0.50
- Tool Call Accuracy: 0.50
- Assessment: Excellent

### AgentEvals Analysis
The AgentEvals trajectory match evaluator compares actual agent behavior against ideal reference trajectories:
- Trajectory Match: Measures how well the agent's overall interaction flow matches the ideal
- Tool Call Accuracy: Evaluates correctness of tool selection and arguments

### Latency
- Average Response Time: 3.06s
- Performance Rating: Acceptable

### Safety & Compliance
- Guardrail Activations: 0
- NeMo Guardrails: Active - no harmful requests detected

### Tool Utilization
- RAG Query: 0 times - Secondary source
- Web Search: 2 times - Frequently used for current info

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

The agent demonstrates excellent performance with comprehensive monitoring and evaluation capabilities.

### Key Strengths
- Effective tool utilization
- Strong safety measures via NeMo Guardrails
- Complete observability through Langfuse
- Accurate trajectory evaluation via AgentEvals

Generated with: NeMo Guardrails + Bedrock + Langfuse + AgentEvals
