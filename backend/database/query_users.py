#!/usr/bin/env python3
"""Quick script to query users from PostgreSQL."""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
ROOT_ENV_PATH = BACKEND_DIR.parent / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH, override=False)

import psycopg2
import json

database_url = os.getenv("DATABASE_URL")
conn = psycopg2.connect(database_url)
cursor = conn.cursor()

# Query all users
cursor.execute("""
    SELECT user_id, email, name, role, skills, color, created_at, last_login
    FROM users
    ORDER BY created_at
""")

users = cursor.fetchall()

print("\n" + "="*80)
print(f"📊 Users in PostgreSQL Database ({len(users)} total)")
print("="*80)

for user_id, email, name, role, skills, color, created_at, last_login in users:
    # PostgreSQL JSONB is already deserialized by psycopg2
    skills_list = skills if isinstance(skills, list) else []
    print(f"\n🔹 {name} ({user_id})")
    print(f"   Email: {email}")
    print(f"   Role: {role}")
    print(f"   Skills: {', '.join(skills_list) if skills_list else 'None'}")
    print(f"   Color: {color}")
    print(f"   Created: {created_at}")
    print(f"   Last Login: {last_login or 'Never'}")

cursor.close()
conn.close()

print("\n" + "="*80)
print("✅ All users retrieved successfully from PostgreSQL!")
print("="*80)
