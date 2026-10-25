"""Project-scoped chat history survives provider outages and process restarts."""
import json
from .db import connect


def load_conversation(db_path, project_id, session_id):
    with connect(db_path) as conn:
        row = conn.execute('SELECT messages_json FROM conversations WHERE project_id=? AND session_id=?',
                           (project_id, session_id)).fetchone()
    return json.loads(row['messages_json']) if row else []


def save_conversation(db_path, project_id, session_id, messages):
    with connect(db_path) as conn:
        conn.execute('INSERT INTO conversations (project_id,session_id,messages_json) VALUES (?,?,?) '
                     'ON CONFLICT(project_id,session_id) DO UPDATE SET messages_json=excluded.messages_json',
                     (project_id, session_id, json.dumps(messages)))
