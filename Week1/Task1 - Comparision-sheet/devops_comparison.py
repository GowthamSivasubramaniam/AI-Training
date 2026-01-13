# """
# DevOps Comparison - CI/CD Pipeline Generation
# Compare GPT-4o, Claude Sonnet 4, Gemini Flash, and DeepSeek Coder
# """

# import os
# from openai import OpenAI
# from anthropic import Anthropic
# import google.generativeai as genai

# # Task: Generate a CI/CD pipeline
PROMPT = """
Create a GitHub Actions CI/CD pipeline (YAML) for a Python web application with the following requirements:

Application Stack:
- Python 3.11 with FastAPI
- PostgreSQL database
- Redis for caching
- Docker for containerization

Pipeline Requirements:
1. Trigger on push to main and pull requests
2. Run on Ubuntu latest
3. Set up Python environment with dependencies
4. Run linting (flake8, black)
5. Run tests with pytest and generate coverage report
6. Build Docker image
7. Push to Docker Hub (on main branch only)
8. Deploy to production (main branch only)
9. Include environment variables and secrets management
10. Add caching for dependencies
11. Parallel jobs where possible
12. Notify on failure

Include proper error handling and best practices.
"""

# def test_gpt4o(api_key):
#     """Test GPT-4o"""
#     print("=" * 80)
#     print("GPT-4o - CI/CD Pipeline Generation")
#     print("=" * 80)
    
#     client = OpenAI(api_key=api_key)
    
#     response = client.chat.completions.create(
#         model='gpt-4o',
#         messages=[
#             {"role": "user", "content": PROMPT}
#         ],
#         temperature=0.7
#     )
    
#     print(response.choices[0].message.content)
#     print("\n")


# def test_claude_sonnet(api_key):
#     """Test Claude Sonnet 4"""
#     print("=" * 80)
#     print("Claude Sonnet 4 - CI/CD Pipeline Generation")
#     print("=" * 80)
    
#     client = Anthropic(api_key=api_key)
    
#     response = client.messages.create(
#         model="claude-sonnet-4-20250514",
#         max_tokens=2000,
#         messages=[
#             {"role": "user", "content": PROMPT}
#         ]
#     )
    
#     print(response.content[0].text)
#     print("\n")


# def test_gemini_flash(api_key):
#     """Test Gemini Flash"""
#     print("=" * 80)
#     print("Gemini Flash - CI/CD Pipeline Generation")
#     print("=" * 80)
    
#     genai.configure(api_key=api_key)
#     model = genai.GenerativeModel('gemini-1.5-flash')
    
#     response = model.generate_content(PROMPT)
#     print(response.text)
#     print("\n")


# def test_deepseek_coder(api_key, base_url="https://api.deepseek.com"):
#     """Test DeepSeek Coder"""
#     print("=" * 80)
#     print("DeepSeek Coder - CI/CD Pipeline Generation")
#     print("=" * 80)
    
#     client = OpenAI(
#         api_key=api_key,
#         base_url=base_url
#     )
    
#     response = client.chat.completions.create(
#         model="deepseek-coder",
#         messages=[
#             {"role": "user", "content": PROMPT}
#         ],
#         temperature=0.7
#     )
    
#     print(response.choices[0].message.content)
#     print("\n")


# if __name__ == "__main__":
#     # Get API keys from environment variables
#     gpt4o_key = os.getenv("OPENAI_API_KEY")
#     claude_key = os.getenv("ANTHROPIC_API_KEY")
#     gemini_key = os.getenv("GOOGLE_API_KEY")
#     deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    
#     print("\n" + "=" * 80)
#     print("DEVOPS COMPARISON - CI/CD PIPELINE GENERATION")
#     print("=" * 80 + "\n")
    
#     # Test each model
#     if gpt4o_key:
#         try:
#             test_gpt4o(gpt4o_key)
#         except Exception as e:
#             print(f"GPT-4o Error: {e}\n")
#     else:
#         print("GPT-4o: No API key provided (OPENAI_API_KEY)\n")
    
#     if claude_key:
#         try:
#             test_claude_sonnet(claude_key)
#         except Exception as e:
#             print(f"Claude Sonnet Error: {e}\n")
#     else:
#         print("Claude Sonnet: No API key provided (ANTHROPIC_API_KEY)\n")
    
#     if gemini_key:
#         try:
#             test_gemini_flash(gemini_key)
#         except Exception as e:
#             print(f"Gemini Flash Error: {e}\n")
#     else:
#         print("Gemini Flash: No API key provided (GOOGLE_API_KEY)\n")
    
#     if deepseek_key:
#         try:
#             test_deepseek_coder(deepseek_key)
#         except Exception as e:
#             print(f"DeepSeek Coder Error: {e}\n")
#     else:
#         print("DeepSeek Coder: No API key provided (DEEPSEEK_API_KEY)\n")



import ollama

client = ollama.Client()

model = "gemma:2b" 
response = client.generate(model=model, prompt=PROMPT)
print(response.response)