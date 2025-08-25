#!/usr/bin/env python3
"""
Telegram Bot that executes Claude CLI commands based on user messages
"""

import subprocess
import requests
import json
import time
import os
import sys
from datetime import datetime
import threading
import re

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BOT_TOKEN = "8268321313:AAH6a-i0A0fxmt7jtXoQ5_PtucT0YwTk8BI"
CHAT_ID = "5246077032"
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Authorized users (add more chat IDs as needed)
AUTHORIZED_USERS = [5246077032]  # Seth van der Bijl

class ClaudeTelegramBot:
    def __init__(self, project_path=None):
        self.running = True
        self.last_update_id = None
        self.project_path = project_path or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.commands_executed = 0
        self.active_process = None
        
    def send_message(self, chat_id, text, parse_mode="Markdown"):
        """Send a message to a chat"""
        url = f"{BASE_URL}/sendMessage"
        
        # Escape markdown if needed
        if parse_mode == "Markdown":
            # Basic markdown escaping for special characters
            text = text.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[")
        
        data = {
            "chat_id": chat_id,
            "text": text[:4096],  # Telegram message limit
            "parse_mode": parse_mode
        }
        
        try:
            response = requests.post(url, json=data)
            return response.json()
        except:
            return {"ok": False}
    
    def get_updates(self, offset=None, timeout=30):
        """Get updates using long polling"""
        url = f"{BASE_URL}/getUpdates"
        params = {"timeout": timeout}
        if offset:
            params["offset"] = offset
        
        try:
            response = requests.get(url, params=params, timeout=timeout+5)
            return response.json()
        except:
            return {"ok": True, "result": []}
    
    def is_authorized(self, chat_id):
        """Check if user is authorized"""
        return chat_id in AUTHORIZED_USERS
    
    def execute_claude_command(self, prompt, chat_id):
        """Execute a Claude CLI command"""
        self.commands_executed += 1
        
        # Send starting message
        self.send_message(chat_id, f"🚀 Executing Claude command #{self.commands_executed}...")
        
        # Build the command
        cmd = [
            "claude",
            "--dangerously-skip-permissions",
            "-p",
            prompt
        ]
        
        try:
            # Change to project directory
            original_dir = os.getcwd()
            os.chdir(self.project_path)
            
            # Execute the command
            self.active_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Start a timer to kill long-running processes
            def timeout_handler():
                time.sleep(120)  # 2 minute timeout
                if self.active_process and self.active_process.poll() is None:
                    self.active_process.kill()
                    self.send_message(chat_id, "⏱️ Command timed out after 2 minutes")
            
            timeout_thread = threading.Thread(target=timeout_handler)
            timeout_thread.daemon = True
            timeout_thread.start()
            
            # Get output
            stdout, stderr = self.active_process.communicate()
            
            # Return to original directory
            os.chdir(original_dir)
            
            if self.active_process.returncode == 0:
                # Success - send output in chunks if needed
                output = stdout[:2000] if stdout else "Command completed with no output"
                
                response = f"✅ **Command Executed Successfully**\n\n"
                response += f"**Output:**\n```\n{output}\n```"
                
                if len(stdout) > 2000:
                    response += f"\n\n_(Output truncated, showing first 2000 chars of {len(stdout)})_"
                
                self.send_message(chat_id, response)
                return True
            else:
                # Error
                error = stderr[:1000] if stderr else "Unknown error"
                response = f"❌ **Command Failed**\n\n**Error:**\n```\n{error}\n```"
                self.send_message(chat_id, response)
                return False
                
        except subprocess.TimeoutExpired:
            self.send_message(chat_id, "⏱️ Command timed out")
            return False
        except Exception as e:
            self.send_message(chat_id, f"❌ Error executing command: {str(e)}")
            return False
        finally:
            self.active_process = None
    
    def process_message(self, message):
        """Process an incoming message"""
        chat_id = message["chat"]["id"]
        text = message.get("text", "")
        from_user = message["from"]
        username = from_user.get("username", "Unknown")
        first_name = from_user.get("first_name", "")
        
        print(f"\n📨 Message from {first_name} (@{username}): {text}")
        
        # Check authorization
        if not self.is_authorized(chat_id):
            self.send_message(chat_id, "❌ Unauthorized. This bot is restricted.")
            return
        
        # Process commands
        if text.startswith("/"):
            self.handle_command(text, chat_id)
        elif text.lower().startswith("claude:"):
            # Execute Claude command
            prompt = text[7:].strip()  # Remove "claude:" prefix
            if prompt:
                self.execute_claude_command(prompt, chat_id)
            else:
                self.send_message(chat_id, "❌ Please provide a prompt after 'claude:'")
        elif text.lower().startswith("run:"):
            # Run a specific task
            task = text[4:].strip()
            self.run_task(task, chat_id)
        else:
            # Treat any other message as a Claude prompt
            if len(text) > 10:  # Only process substantial messages
                self.execute_claude_command(text, chat_id)
            else:
                self.send_message(chat_id, "💡 Send a longer message or use:\n• `claude: <prompt>`\n• `run: <task>`\n• `/help` for more info")
    
    def handle_command(self, command, chat_id):
        """Handle bot commands"""
        cmd = command.lower().strip()
        
        if cmd == "/start":
            welcome = """🤖 **Claude Telegram Bot**

I can execute Claude CLI commands for you!

**How to use:**
• Send any message and I'll run it through Claude
• Or use: `claude: <your prompt>`
• Or use: `run: <task name>`

**Commands:**
/help - Show this help
/status - Bot status
/tasks - Show available tasks
/stop - Stop current command
/stats - Show statistics"""
            self.send_message(chat_id, welcome)
            
        elif cmd == "/help":
            help_text = """📚 **Help**

**Usage Examples:**
• `List all Python files`
• `claude: Create a hello world script`
• `run: test backlog`

**Commands:**
/status - Check bot status
/tasks - Show predefined tasks
/stop - Stop running command
/stats - Show statistics
/project - Show project path"""
            self.send_message(chat_id, help_text)
            
        elif cmd == "/status":
            status = f"""✅ **Bot Status**

• **Active:** Yes
• **Commands executed:** {self.commands_executed}
• **Project path:** {self.project_path}
• **Process running:** {'Yes' if self.active_process else 'No'}
• **Time:** {datetime.now().strftime('%H:%M:%S')}"""
            self.send_message(chat_id, status)
            
        elif cmd == "/tasks":
            tasks = """📋 **Available Tasks**

• `run: test backlog` - Run test backlog
• `run: list files` - List Python files
• `run: check status` - Check system status
• `run: create test` - Create a test file

Or send any custom prompt!"""
            self.send_message(chat_id, tasks)
            
        elif cmd == "/stop":
            if self.active_process:
                self.active_process.kill()
                self.send_message(chat_id, "🛑 Current command stopped")
            else:
                self.send_message(chat_id, "No command is currently running")
                
        elif cmd == "/stats":
            stats = f"""📊 **Statistics**

• Commands executed: {self.commands_executed}
• Bot uptime: Active
• Authorized users: {len(AUTHORIZED_USERS)}"""
            self.send_message(chat_id, stats)
            
        elif cmd == "/project":
            self.send_message(chat_id, f"📁 Project path: `{self.project_path}`")
            
        else:
            self.send_message(chat_id, f"❓ Unknown command: {command}")
    
    def run_task(self, task, chat_id):
        """Run predefined tasks"""
        tasks = {
            "test backlog": "Run the test backlog processing with 1 item",
            "list files": "List all Python files in the current directory",
            "check status": "Check the status of the backlog processing system",
            "create test": "Create a simple test file called telegram_test.txt with current timestamp"
        }
        
        task_lower = task.lower()
        
        if task_lower in tasks:
            prompt = tasks[task_lower]
            self.execute_claude_command(prompt, chat_id)
        else:
            available = "\n• ".join(tasks.keys())
            self.send_message(chat_id, f"❓ Unknown task: {task}\n\nAvailable tasks:\n• {available}")
    
    def run(self):
        """Main bot loop"""
        print("🤖 Claude Telegram Bot Starting...")
        print(f"Project path: {self.project_path}")
        print("="*60)
        
        # Send startup notification
        self.send_message(CHAT_ID, "🤖 Claude Telegram Bot is now active!\n\nSend me a message or command to execute through Claude CLI.")
        
        print("📡 Listening for messages...")
        print("Send a message to @pitchai_dev_bot")
        print("Press Ctrl+C to stop")
        print("="*60)
        
        while self.running:
            try:
                updates = self.get_updates(offset=self.last_update_id, timeout=30)
                
                if updates.get("ok"):
                    for update in updates["result"]:
                        update_id = update["update_id"]
                        
                        if self.last_update_id is None or update_id > self.last_update_id:
                            self.last_update_id = update_id + 1
                        
                        if "message" in update:
                            self.process_message(update["message"])
                
            except KeyboardInterrupt:
                print("\n🛑 Stopping bot...")
                self.running = False
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                time.sleep(5)
        
        # Send shutdown notification
        self.send_message(CHAT_ID, "👋 Claude Telegram Bot has stopped")
        print("✅ Bot stopped")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Claude Telegram Bot")
    parser.add_argument("--project", help="Project path", default=None)
    args = parser.parse_args()
    
    # Check if Claude CLI is available
    try:
        subprocess.run(["claude", "--version"], capture_output=True, check=True)
    except:
        print("❌ Claude CLI not found. Please install it first.")
        sys.exit(1)
    
    bot = ClaudeTelegramBot(project_path=args.project)
    
    try:
        bot.run()
    except Exception as e:
        print(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()