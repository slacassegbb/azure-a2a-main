#!/usr/bin/env python3
"""Deploy agent schema to PostgreSQL database."""

import psycopg2
import os
from pathlib import Path

# Get DATABASE_URL from environment or use default
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print('⚠️  DATABASE_URL not found in environment, using connection from auth_service')
    # Try to get from the same place auth_service uses
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from service.auth_service import AuthService
        
        # Create temp instance to check database URL
        temp_service = AuthService(user_file='dummy.json')
        if hasattr(temp_service, 'database_url') and temp_service.database_url:
            DATABASE_URL = temp_service.database_url
            print(f'✅ Found DATABASE_URL from AuthService')
        else:
            print('❌ No DATABASE_URL available')
            exit(1)
    except Exception as e:
        print(f'❌ Could not get DATABASE_URL: {e}')
        exit(1)

print('Deploying agent schema to PostgreSQL...\n')

# Connect and deploy schema
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# Read schema file
schema_file = Path(__file__).parent / 'agent_schema.sql'
with open(schema_file, 'r') as f:
    schema_sql = f.read()

# Execute schema
cur.execute(schema_sql)
conn.commit()

print('✅ Agent schema deployed successfully')

# Verify table exists
cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'agents'
    ORDER BY ordinal_position
""")

columns = cur.fetchall()
print(f'\n✅ Agents table created with {len(columns)} columns:')
for col_name, col_type in columns:
    print(f'   - {col_name}: {col_type}')

cur.close()
conn.close()

print('\n✅ Database ready for agent registry migration')
