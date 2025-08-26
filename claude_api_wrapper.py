#!/usr/bin/env python3
"""
Working Claude CLI wrapper using the Claude Code OAuth token.
This uses the official Claude API with proper authentication.
"""
import os
import sys
import argparse
import requests
import json

def main():
    parser = argparse.ArgumentParser(description="Claude CLI wrapper")
    parser.add_argument("--dangerously-skip-permissions", action="store_true", help="Skip permission checks")
    parser.add_argument("-p", "--prompt-file", help="File containing the prompt")
    parser.add_argument("prompt", nargs="?", help="Direct prompt text")
    
    args = parser.parse_args()
    
    # Get OAuth token from environment
    oauth_token = os.getenv('CLAUDE_CODE_OAUTH_TOKEN')
    if not oauth_token:
        print("Error: No Claude OAuth token found. Set CLAUDE_CODE_OAUTH_TOKEN", file=sys.stderr)
        sys.exit(1)
    
    # Read prompt from file or command line
    if args.prompt_file:
        try:
            with open(args.prompt_file, 'r') as f:
                prompt = f.read()
        except FileNotFoundError:
            print(f"Error: Prompt file {args.prompt_file} not found", file=sys.stderr)
            sys.exit(1)
    elif args.prompt:
        prompt = args.prompt
    else:
        print("Error: No prompt provided", file=sys.stderr)
        sys.exit(1)
    
    try:
        # Use Claude API with OAuth token
        # Note: This uses the standard Anthropic API since we have the OAuth token
        headers = {
            'Authorization': f'Bearer {oauth_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        payload = {
            'model': 'claude-3-5-sonnet-20241022',
            'max_tokens': 4000,
            'messages': [
                {'role': 'user', 'content': prompt}
            ]
        }
        
        # Make API call to Anthropic
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers=headers,
            json=payload,
            timeout=120
        )
        
        if response.status_code == 200:
            result = response.json()
            # Extract and print the response content
            if result.get('content') and len(result['content']) > 0:
                print(result['content'][0]['text'])
            else:
                print("No content in response")
        else:
            print(f"Error: HTTP {response.status_code}: {response.text}", file=sys.stderr)
            sys.exit(1)
            
    except Exception as e:
        print(f"Error calling Claude API: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()