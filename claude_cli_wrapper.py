#!/usr/bin/env python3
"""
Simple wrapper for Claude CLI functionality using Anthropic API directly.
This is used when the official Claude Code CLI is not available in containers.
"""
import os
import sys
import argparse
from anthropic import Anthropic

def main():
    parser = argparse.ArgumentParser(description="Claude CLI wrapper")
    parser.add_argument("--dangerously-skip-permissions", action="store_true", help="Skip permission checks")
    parser.add_argument("-p", "--prompt-file", help="File containing the prompt")
    parser.add_argument("prompt", nargs="?", help="Direct prompt text")
    
    args = parser.parse_args()
    
    # Get API key from environment
    api_key = os.getenv('CLAUDE_CODE_OAUTH_TOKEN') or os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        print("Error: No Claude API key found. Set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY", file=sys.stderr)
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
        # Initialize Anthropic client
        client = Anthropic(api_key=api_key)
        
        # Send message to Claude
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        # Print response
        print(response.content[0].text)
        
    except Exception as e:
        print(f"Error calling Claude API: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()