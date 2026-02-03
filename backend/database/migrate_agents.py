#!/usr/bin/env python3
"""Migrate agents from JSON to PostgreSQL database."""

import json
import psycopg2
from pathlib import Path

DATABASE_URL = "postgresql://pgadmin:Hip1hops!@a2adb.postgres.database.azure.com:5432/postgres"

print('='*70)
print('AGENT REGISTRY MIGRATION: JSON → PostgreSQL')
print('='*70)

# Load agents from unified JSON
json_file = Path(__file__).parent.parent / 'data' / 'agent_registry_unified.json'
print(f'\nLoading agents from: {json_file.name}')

with open(json_file, 'r') as f:
    agents = json.load(f)

print(f'✅ Loaded {len(agents)} agents from JSON')

# Connect to database
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# Clear existing agents (for clean migration)
cur.execute('DELETE FROM agents')
print(f'\n🗑️  Cleared existing agents from database')

# Insert each agent
inserted = 0
for agent in agents:
    try:
        cur.execute("""
            INSERT INTO agents (
                name, description, version,
                local_url, production_url,
                default_input_modes, default_output_modes,
                capabilities, skills
            ) VALUES (
                %s, %s, %s,
                %s, %s,
                %s::jsonb, %s::jsonb,
                %s::jsonb, %s::jsonb
            )
        """, (
            agent.get('name'),
            agent.get('description'),
            agent.get('version'),
            agent.get('local_url'),
            agent.get('production_url'),
            json.dumps(agent.get('defaultInputModes', [])),
            json.dumps(agent.get('defaultOutputModes', [])),
            json.dumps(agent.get('capabilities', {})),
            json.dumps(agent.get('skills', []))
        ))
        inserted += 1
        print(f'  ✓ Migrated: {agent.get("name")}')
    except Exception as e:
        print(f'  ✗ Failed: {agent.get("name")} - {e}')

conn.commit()

# Verify migration
cur.execute('SELECT COUNT(*) FROM agents')
count = cur.fetchone()[0]

print(f'\n{"="*70}')
print(f'✅ Migration complete!')
print(f'   - Inserted: {inserted} agents')
print(f'   - Database count: {count} agents')

# Show sample agents
cur.execute("""
    SELECT name, local_url, production_url 
    FROM agents 
    ORDER BY name 
    LIMIT 5
""")

print(f'\n📋 Sample agents in database:')
for name, local_url, prod_url in cur.fetchall():
    print(f'   - {name}')
    print(f'     Local: {local_url[:50]}...' if len(local_url) > 50 else f'     Local: {local_url}')
    print(f'     Prod:  {prod_url[:50]}...' if len(prod_url) > 50 else f'     Prod:  {prod_url}')

cur.close()
conn.close()

print(f'\n✅ Agents now stored in PostgreSQL database!')
print('='*70)
