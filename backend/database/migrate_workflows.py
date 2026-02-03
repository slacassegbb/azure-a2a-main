#!/usr/bin/env python3
"""Migrate workflows from JSON to PostgreSQL database."""

import json
import psycopg2
from pathlib import Path

DATABASE_URL = "postgresql://pgadmin:Hip1hops!@a2adb.postgres.database.azure.com:5432/postgres"

print('='*70)
print('WORKFLOW MIGRATION: JSON → PostgreSQL')
print('='*70)

json_file = Path(__file__).parent.parent / 'data' / 'workflows.json'
print(f'\nLoading workflows from: {json_file.name}')

with open(json_file, 'r') as f:
    data = json.load(f)
    workflows = data.get('workflows', [])

print(f'✅ Loaded {len(workflows)} workflows from JSON')

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

cur.execute('DELETE FROM workflows')
print(f'\n🗑️  Cleared existing workflows from database')

inserted = 0
for workflow in workflows:
    try:
        cur.execute("""
            INSERT INTO workflows (
                id, name, description, category, user_id,
                steps, connections, goal, is_custom,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s, %s,
                %s, %s
            )
        """, (
            workflow.get('id'),
            workflow.get('name'),
            workflow.get('description'),
            workflow.get('category'),
            workflow.get('user_id'),
            json.dumps(workflow.get('steps', [])),
            json.dumps(workflow.get('connections', [])),
            workflow.get('goal'),
            workflow.get('is_custom', True),
            workflow.get('created_at'),
            workflow.get('updated_at')
        ))
        inserted += 1
        print(f'  ✓ Migrated: {workflow.get("name")} (user: {workflow.get("user_id")})')
    except Exception as e:
        print(f'  ✗ Failed: {workflow.get("name")} - {e}')

conn.commit()

cur.execute('SELECT COUNT(*) FROM workflows')
count = cur.fetchone()[0]

print(f'\n{"="*70}')
print(f'✅ Migration complete!')
print(f'   - Inserted: {inserted} workflows')
print(f'   - Database count: {count} workflows')

cur.execute("""
    SELECT id, name, user_id, category
    FROM workflows 
    ORDER BY created_at DESC
""")

print(f'\n📋 Workflows in database:')
for wf_id, name, user_id, category in cur.fetchall():
    print(f'   - {name} ({category}) - User: {user_id}')

cur.close()
conn.close()

print(f'\n✅ Workflows now stored in PostgreSQL database!')
print('='*70)
