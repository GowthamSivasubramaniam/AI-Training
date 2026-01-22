"""
Google Docs MCP Server - Read Only Version
Simple server that only reads Google Docs content
"""

import asyncio
from pathlib import Path

from mcp.server import Server

from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# Read-only scope
SCOPES = ['https://www.googleapis.com/auth/documents.readonly']

class GoogleDocsReadServer:
    def __init__(self):
        self.app = Server("google-docs-read")
        self.service = None
        self.setup_handlers()
        
    def authenticate(self):
        """Handle Google OAuth authentication"""
        creds = None
        token_path = Path("token.json")
        creds_path = Path("Week4/credentials.json")
        
        # Check for existing token
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        
        # If no valid credentials, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not creds_path.exists():
                    raise FileNotFoundError(
                        "credentials.json not found. "
                        "Please download it from Google Cloud Console"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(creds_path), SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # Save credentials
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
        
        # Build the service
        self.service = build('docs', 'v1', credentials=creds)
        return self.service

    def setup_handlers(self):
        """Set up MCP protocol handlers"""
        
        @self.app.list_tools()
        async def list_tools() -> list[Tool]:
            """List available tools - only read_document"""
            return [
                Tool(
                    name="read_document",
                    description="Read content from a Google Doc by document ID. The document ID is the long string in the URL: https://docs.google.com/document/d/DOCUMENT_ID/edit",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "document_id": {
                                "type": "string",
                                "description": "The Google Doc ID from the URL"
                            }
                        },
                        "required": ["document_id"]
                    }
                ),
            ]
        
        @self.app.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            """Handle tool execution"""
            try:
                if name == "read_document":
                    return await self.read_document(arguments["document_id"])
                else:
                    return [TextContent(
                        type="text",
                        text=f"Unknown tool: {name}"
                    )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=f"Error: {str(e)}"
                )]

    async def read_document(self, document_id: str) -> list[TextContent]:
        """Read content from a Google Doc"""
        try:
            # Get the document
            document = self.service.documents().get(documentId=document_id).execute()
            
            # Extract text content
            content = []
            doc_content = document.get('body', {}).get('content', [])
            
            for element in doc_content:
                if 'paragraph' in element:
                    for text_run in element['paragraph'].get('elements', []):
                        if 'textRun' in text_run:
                            content.append(text_run['textRun']['content'])
            
            full_text = ''.join(content)
            doc_title = document.get('title', 'Untitled')
            
            return [TextContent(
                type="text",
                text=f"Document: {doc_title}\n{'='*50}\n\n{full_text}"
            )]
            
        except HttpError as e:
            if e.resp.status == 404:
                return [TextContent(
                    type="text",
                    text=f"Error: Document not found. Please check the document ID."
                )]
            elif e.resp.status == 403:
                return [TextContent(
                    type="text",
                    text=f"Error: Permission denied. Make sure you have access to this document."
                )]
            else:
                return [TextContent(
                    type="text",
                    text=f"Error reading document: {str(e)}"
                )]

    async def run(self):
        """Run the MCP server"""
        # Authenticate with Google
        print("Authenticating with Google Docs...")
        self.authenticate()
        print("Authentication successful! Server is running.")
        
        # Start the server
        async with stdio_server() as (read_stream, write_stream):
            await self.app.run(
                read_stream,
                write_stream,
                self.app.create_initialization_options()
            )


async def main():
    """Main entry point"""
    server = GoogleDocsReadServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())