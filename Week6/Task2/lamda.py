import json
import requests
from bs4 import BeautifulSoup
import re

MAX_BYTES = 1_000_000

def lambda_handler(event, context):
    print("Received event:", json.dumps(event))
    
    # Extract parameters
    action_group = event.get('actionGroup', '')
    function_name = event.get('function', '')
    input_text = event.get('inputText', '')
    
    # Extract URL from inputText using regex
    url_match = re.search(r'https?://[^\s]+', input_text)
    url = url_match.group(0) if url_match else None
    
    # Helper function for error response
    def create_error_response(error_msg):
        return {
            'messageVersion': '1.0',
            'response': {
                'actionGroup': action_group,
                'function': function_name,
                'functionResponse': {
                    'responseState': 'FAILURE',
                    'responseBody': {
                        'TEXT': {
                            'body': json.dumps({'error': error_msg})
                        }
                    }
                }
            }
        }
    
    if not url:
        return create_error_response('No URL found in input')
    
    try:
        headers = {
            "User-Agent": "Bedrock-Web-Crawler/1.0",
            "Accept-Encoding": "gzip"
        }
        
        response = requests.get(
            url,
            headers=headers,
            timeout=10,
            allow_redirects=True,
            stream=True
        )
        
        content = response.content[:MAX_BYTES]
        soup = BeautifulSoup(content, "html.parser")
        
        # Remove scripts & styles
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        
        text = " ".join(soup.stripped_strings)
        
        # Success response - NO responseState for success
        return {
            'messageVersion': '1.0',
            'response': {
                'actionGroup': action_group,
                'function': function_name,
                'functionResponse': {
                    'responseBody': {
                        'TEXT': {
                            'body': json.dumps({
                                'url': response.url,
                                'status': response.status_code,
                                'text': text[:5000]
                            })
                        }
                    }
                }
            }
        }
    
    except Exception as e:
        print(f"Error: {str(e)}")
        return create_error_response(str(e))