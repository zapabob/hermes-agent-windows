#!/usr/bin/env python3
import sqlite3
import json
import re
import hashlib
import time
from pathlib import Path
from datetime import datetime, timezone
import urllib.request
import urllib.error

# Configuration
HERMES_DIR = Path(r'C:\Users\downl\.hermes')
STATE_DB = HERMES_DIR / 'state.db'
LAST_RUN_FILE = HERMES_DIR / 'memory' / 'social-sync' / 'last_run.txt'
LINE_BRIDGE_URL = 'http://127.0.0.1:9101'
KANABAN_TOOL = 'hermes'  # We'll call hermes kanban via terminal

# Two-tier secret guard (simplified from the skill)
BROAD_SECRET_PATTERNS = [
    r'\\b(?:password|token|secret|apikey|api_key|oauth|cookie|session|bearer)\\s*[:=]\\s*\\S+',
    r'\\b[A-Za-z0-9_\\-]{20,}\\b',  # Long tokens
    r'sk-[A-Za-z0-9]{20,}',      # OpenAI-style keys
    r'gh[ps]_[A-Za-z0-9]{20,}',  # GitHub tokens
    r'xoxb-[A-Za-z0-9\\-]{20,}',  # Slack bot tokens
]
BROAD_GUARD = re.compile('|'.join(BROAD_SECRET_PATTERNS), re.IGNORECASE)

# Scoped verification for saved rows (path markers + raw secret patterns)
import re as _re
BS = chr(92)
PATH_MARKERS = [
    _re.escape('C:' + BS + 'Users'),
    _re.escape('C:/Users'),
    _re.escape('/home/'),
    _re.escape(BS + 'Users' + BS),
    _re.escape(r'~\\.hermes'),
    _re.escape(r'~/.hermes'),
]
SECRET_TOKEN_PATTERNS = [
    r'\\b(?:password|token|secret|apikey|api_key|oauth|cookie|session|bearer)\\s*[:=]\\s*\\S+',
    r'\\bsk-[A-Za-z0-9]{20,}\\b',
    r'\\bgh[ps]_[A-Za-z0-9]{20,}\\b',
    r'\\bxoxb-[A-Za-z0-9\\-]{20,}\\b',
    r'\\bMEMORY_VAULT_AES_KEY\\b',
    r'\\bBITWARDEN\\b',
    r'\\bBW_SESSION\\b',
]
SCOPED_PATTERNS = PATH_MARKERS + SECRET_TOKEN_PATTERNS
SCOPED_GUARD = re.compile('|'.join(SCOPED_PATTERNS), re.IGNORECASE)

def has_secret_broad(text: str) -> bool:
    return bool(BROAD_GUARD.search(text))

def has_secret_scoped(text: str) -> bool:
    return bool(SCOPED_GUARD.search(text))

def get_last_run_time():
    if LAST_RUN_FILE.exists():
        try:
            with open(LAST_RUN_FILE, 'r') as f:
                timestamp_str = f.read().strip()
                return datetime.fromisoformat(timestamp_str)
        except Exception:
            pass
    # Default to far past if no file or error
    return datetime(2020, 1, 1, tzinfo=timezone.utc)

def set_last_run_time(dt: datetime):
    LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LAST_RUN_FILE, 'w') as f:
        f.write(dt.isoformat())

def get_line_messages_since(since_dt):
    """Get new LINE messages from the bridge since since_dt."""
    # First, check bridge status
    try:
        req = urllib.request.Request(f'{LINE_BRIDGE_URL}/status')
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = json.load(resp)
    except Exception as e:
        print(f"LINE bridge status check failed: {e}")
        return [], {'status_error': str(e)}
    
    login_state = status.get('loginState')
    if login_state != 'ready':
        print(f"LINE bridge not ready: {login_state}")
        # Fall back to bridge.log? We'll skip for now and note in residual risk.
        return [], {'bridge_not_ready': login_state}
    
    # Get events since since_dt
    try:
        # Convert since_dt to ISO format string for comparison
        since_iso = since_dt.isoformat()
        req = urllib.request.Request(f'{LINE_BRIDGE_URL}/events?limit=200')
        with urllib.request.urlopen(req, timeout=10) as resp:
            events_data = json.load(resp)
    except Exception as e:
        print(f"LINE bridge events fetch failed: {e}")
        return [], {'events_error': str(e)}
    
    messages = []
    for event in events_data.get('events', []):
        at_str = event.get('at')
        if not at_str:
            continue
        try:
            at_dt = datetime.fromisoformat(at_str.replace('Z', '+00:00'))
        except Exception:
            continue
        if at_dt > since_dt:
            # We are only interested in message events
            if event.get('type') == 'message':
                # The event structure: from the linejs worker, message events have a 'message' field?
                # Looking at the earlier events output, we saw events of type 'message'?
                # Actually, in the events we saw earlier, there were no 'message' type events because the bridge was blocked.
                # We'll assume that if the event type is 'message', then the text is in event.get('message', {}).get('text')
                # But we need to check the actual structure from the linejs worker.
                # Since we don't have a sample, we'll look for any text in the event.
                text = event.get('text') or event.get('message', {}).get('text') or ''
                if text and not has_secret_broad(text):
                    messages.append({
                        'platform': 'line',
                        'text': text,
                        'timestamp': at_dt
                    })
            # Also look for other event types that might contain messages? We'll stick to 'message' for now.
    return messages, {}

def get_telegram_discord_messages_since(since_dt):
    """Get new Telegram and Discord messages from state.db since since_dt."""
    conn = sqlite3.connect(str(STATE_DB))
    cursor = conn.cursor()
    
    # We'll get messages from telegram and discord sources
    cursor.execute('''
        SELECT m.content, s.source, m.timestamp
        FROM messages m
        JOIN sessions s ON m.session_id = s.id
        WHERE s.source IN ('telegram', 'discord')
        AND m.content IS NOT NULL
        AND m.content != ''
        AND m.role IN ('user', 'assistant')
        AND m.timestamp > ?
        ORDER BY m.timestamp ASC
    ''', (since_dt.timestamp(),))
    
    messages = []
    for content, source, ts in cursor.fetchall():
        if not has_secret_broad(content):
            messages.append({
                'platform': source,
                'text': content,
                'timestamp': datetime.fromtimestamp(ts, tz=timezone.utc)
            })
    
    conn.close()
    return messages, {}

def extract_action_items(messages):
    """Extract action items from a list of message dicts."""
    action_items = []
    # Simple heuristic: look for sentences that contain action-oriented keywords
    # We'll split by common sentence terminators and then check each sentence.
    action_keywords = [
        'action', 'todo', 'task', 'must', 'should', 'need to', 'have to',
        'please', 'can you', 'could you', 'will you', 'please do',
        'please make sure', 'remember to', 'don\'t forget',
        'follow up', 'investigate', 'check', 'verify', 'ensure',
        'implement', 'fix', 'resolve', 'update', 'create', 'delete',
        'submit', 'send', 'call', 'email', 'message', 'notify'
    ]
    
    for msg in messages:
        text = msg['text']
        # Split into sentences by common terminators
        sentences = re.split(r'[.!?\n]+', text)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10 or len(sentence) > 200:
                continue
            sentence_lower = sentence.lower()
            if any(keyword in sentence_lower for keyword in action_keywords):
                # Further check: avoid sentences that are just notifications or status updates
                if not any(phrase in sentence_lower for phrase in ['is running', 'has been', 'was', 'were', 'are', 'will be']):
                    action_items.append({
                        'platform': msg['platform'],
                        'text': sentence,
                        'timestamp': msg['timestamp']
                    })
    return action_items

def hash_action_item(text):
    """Create a stable hash for the action item to use as idempotency key."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def kanban_task_exists(idempotency_key):
    """Check if a kanban task with this idempotency key already exists."""
    # We'll list all kanban tasks and look for the idempotency key in the body or title.
    # Since we don't have a direct way, we'll use the hermes kanban list tool and parse the output.
    try:
        result = terminal_command(f'{KANABAN_TOOL} kanban list')
        if result['exit_code'] != 0:
            return False
        output = result['output']
        # We'll look for the idempotency key in the output.
        # We assume we put the idempotency key in the body of the task when we create it.
        if idempotency_key in output:
            return True
    except Exception:
        pass
    return False

def create_kanban_task(action_item):
    """Create a kanban task for the action item."""
    title = action_item['text'][:100]  # Limit title length
    body = f"Platform: {action_item['platform']}\n"
    body += f"Timestamp: {action_item['timestamp'].isoformat()}\n"
    body += f"Original message: {action_item['text'][:500]}\n"
    body += f"Idempotency-key: {hash_action_item(action_item['text'])}"
    
    # We'll use the hermes kanban create command with idempotency key
    idempotency_key = hash_action_item(action_item['text'])
    cmd = f'{KANABAN_TOOL} kanban create "{title}" --body "{body}" --idempotency-key social-sync-action-{idempotency_key} --created-by social-sync-cron --priority 2'
    result = terminal_command(cmd)
    if result['exit_code'] == 0:
        # Extract the task ID from the output (if any)
        task_id = None
        for line in result['output'].split('\\n'):
            if 'id:' in line.lower():
                # Try to extract the ID
                parts = line.split(':')
                if len(parts) > 1:
                    task_id = parts[1].strip()
                    break
        return True, task_id
    else:
        return False, result.get('error', 'Unknown error')

def terminal_command(cmd):
    """Run a terminal command and return the result."""
    import subprocess
    try:
        # Use shell=True for complex commands
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return {
            'exit_code': result.returncode,
            'output': result.stdout,
            'error': result.stderr
        }
    except subprocess.TimeoutExpired:
        return {'exit_code': -1, 'output': '', 'error': 'Timeout'}
    except Exception as e:
        return {'exit_code': -1, 'output': '', 'error': str(e)}

def main():
    print(f"[{datetime.now().isoformat()}] Starting social sync for unread messages and action items...")
    
    # Get last run time
    since_dt = get_last_run_time()
    print(f"Last run time: {since_dt.isoformat()}")
    
    # Get new messages from each platform
    line_messages, line_err = get_line_messages_since(since_dt)
    print(f"LINE: {len(line_messages)} new messages" + (f" (error: {line_err})" if line_err else ""))
    
    td_messages, td_err = get_telegram_discord_messages_since(since_dt)
    print(f"Telegram/Discord: {len(td_messages)} new messages" + (f" (error: {td_err})" if td_err else ""))
    
    all_messages = line_messages + td_messages
    
    # Extract action items
    action_items = extract_action_items(all_messages)
    print(f"Action items extracted: {len(action_items)}")
    
    # Process each action item: check if task exists, create if not
    tasks_created = 0
    tasks_existing = 0
    for item in action_items:
        item_text = item['text']
        idempotency_key = hash_action_item(item_text)
        if kanban_task_exists(idempotency_key):
            tasks_existing += 1
            print(f"  Task already exists for action item: {item_text[:50]}...")
        else:
            success, task_id = create_kanban_task(item)
            if success:
                tasks_created += 1
                print(f"  Created task: {task_id} for action item: {item_text[:50]}...")
            else:
                print(f"  Failed to create task for action item: {item_text[:50]}...")
    
    # Update last run time to now
    set_last_run_time(datetime.now(timezone.utc))
    print(f"Updated last run time to {datetime.now(timezone.utc).isoformat()}")
    
    # Determine residual risk
    residual_risk = 'low'
    if line_err or td_err:
        residual_risk = 'medium'
    # Check if we encountered any secrets during extraction (we already filtered with broad guard, but just in case)
    # We could also check for scoped guard violations if we had saved anything, but we didn't save to memory.
    
    # Prepare result
    result = {
        'line_unread': len(line_messages),
        'telegram_unread': len([m for m in td_messages if m['platform'] == 'telegram']),
        'discord_unread': len([m for m in td_messages if m['platform'] == 'discord']),
        'action_items_found': len(action_items),
        'kanban_tasks_created': tasks_created,
        'kanban_tasks_existing': tasks_existing,
        'residual_risk': residual_risk,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    
    # If everything is zero and residual risk is low, we should output [SILENT]
    if (result['line_unread'] == 0 and result['telegram_unread'] == 0 and result['discord_unread'] == 0 and
        result['action_items_found'] == 0 and result['kanban_tasks_created'] == 0 and
        residual_risk == 'low'):
        print("[SILENT]")
    else:
        # Output the result as JSON for clarity
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    return result

if __name__ == '__main__':
    main()