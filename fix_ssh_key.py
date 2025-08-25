#!/usr/bin/env python3
"""
Script to fix the SSH key formatting in GitHub secrets.
Converts \\n escape sequences to actual newlines for proper SSH key parsing.
"""
import os
import subprocess
import sys

def read_ssh_key_from_env():
    """Read SSH key from .env file and convert \\n to actual newlines"""
    env_file = '.env'
    if not os.path.exists(env_file):
        print(f"Error: {env_file} file not found")
        return None
    
    with open(env_file, 'r') as f:
        for line in f:
            if line.startswith('HETZNER_SSH_KEY='):
                # Extract the key value, removing quotes
                key_value = line.split('=', 1)[1].strip()
                if key_value.startswith('"') and key_value.endswith('"'):
                    key_value = key_value[1:-1]
                
                # Convert \\n to actual newlines
                formatted_key = key_value.replace('\\n', '\n')
                return formatted_key
    
    print("Error: HETZNER_SSH_KEY not found in .env file")
    return None

def update_github_secret(secret_name, secret_value):
    """Update GitHub secret using gh CLI"""
    try:
        # Use gh CLI to update the secret
        cmd = ['gh', 'secret', 'set', secret_name]
        process = subprocess.run(
            cmd,
            input=secret_value,
            text=True,
            capture_output=True,
            check=True
        )
        print(f"Successfully updated GitHub secret: {secret_name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error updating GitHub secret: {e}")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        return False

def main():
    print("🔧 Fixing SSH key formatting for GitHub Actions...")
    
    # Read SSH key from .env
    ssh_key = read_ssh_key_from_env()
    if not ssh_key:
        sys.exit(1)
    
    print("✅ Successfully read SSH key from .env file")
    print("🔍 Key format preview:")
    print(f"   Starts with: {ssh_key[:50]}...")
    print(f"   Ends with: ...{ssh_key[-50:]}")
    print(f"   Length: {len(ssh_key)} characters")
    print(f"   Newlines: {ssh_key.count(chr(10))} actual newlines found")
    
    # Update GitHub secret
    if update_github_secret('HETZNER_SSH_KEY', ssh_key):
        print("✅ GitHub secret updated successfully!")
        print("🚀 The SSH key now has proper newline formatting for GitHub Actions")
        return True
    else:
        print("❌ Failed to update GitHub secret")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)