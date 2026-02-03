#!/usr/bin/env python3
"""Deploy schedule_run_history table schema to PostgreSQL."""

import os
import sys
import psycopg2

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://pgadmin:Hip1hops!@a2adb.postgres.database.azure.com:5432/postgres')

def deploy_schema():
    """Deploy the schema to PostgreSQL."""
    print("🚀 Deploying schedule_run_history schema...")
    
    # Read schema file
    schema_file = os.path.join(os.path.dirname(__file__), 'schedule_run_history_schema.sql')
    with open(schema_file, 'r') as f:
        schema = f.read()
    
    # Connect and execute
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        cur.execute(schema)
        conn.commit()
        
        # Verify table was created
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'schedule_run_history'
            ORDER BY ordinal_position;
        """)
        
        columns = cur.fetchall()
        print(f"\n✅ Schedule_run_history table created with {len(columns)} columns:")
        for col, dtype in columns:
            print(f"  - {col}: {dtype}")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error deploying schema: {e}")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()
    
    print("\n✅ Schema deployment complete!")

if __name__ == "__main__":
    deploy_schema()
