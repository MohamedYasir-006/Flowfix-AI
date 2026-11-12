"""Rotate the demo agent key and print it. Usage: python scripts/demo_key.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import init_db, SessionLocal
from app.models import Agent
from app.security import generate_agent_key, hash_key

init_db()
db = SessionLocal()
try:
    agent = db.get(Agent, "agent-support")
    if agent is None:
        print("agent-support not found", file=sys.stderr)
        sys.exit(1)
    key = generate_agent_key()
    agent.credential_hash = hash_key(key)
    db.commit()
    print(key)
finally:
    db.close()
