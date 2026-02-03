#!/usr/bin/env python3
"""Migrate schedule run history from JSON to PostgreSQL."""

import os
import sys
import json
from pathlib import Path
import psycopg2
from datetime import datetime

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://pgadmin:Hip1hops!@a2adb.postgres.database.azure.com:5432/postgres')

def migrate_run_history():
    """Migrate run history from JSON file to PostgreSQL."""
    
    # Load existing run history
    history_file = Path(__file__).parent.parent / 'data' / 'schedule_run_history.json'
    
    if not history_file.exists():
        print(f"❌ Run history file not found: {history_file}")
        return
    
    with open(history_file, 'r') as f:
        history_entries = json.load(f)
    
    print(f"📊 Found {len(history_entries)} run history entries to migrate")
    
    # Connect to database
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    inserted = 0
    skipped = 0
    errors = 0
    
    for entry in history_entries:
        try:
            # Skip entries with non-UUID schedule_id (like "on-demand")
            schedule_id = entry.get('schedule_id')
            if not schedule_id or schedule_id == 'on-demand':
                print(f"⏭️  Skipping on-demand entry {entry.get('run_id')}")
                skipped += 1
                continue
            
            # Parse datetime strings
            timestamp = entry.get('timestamp')
            started_at = entry.get('started_at')
            completed_at = entry.get('completed_at')
            
            # Convert ISO strings to datetime objects if needed
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            if isinstance(started_at, str):
                started_at = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            if isinstance(completed_at, str):
                completed_at = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
            
            # Insert into database (using ON CONFLICT to skip duplicates)
            cur.execute("""
                INSERT INTO schedule_run_history (
                    run_id,
                    schedule_id,
                    workflow_id,
                    workflow_name,
                    session_id,
                    timestamp,
                    started_at,
                    completed_at,
                    duration_seconds,
                    status,
                    result,
                    error
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (run_id) DO NOTHING
            """, (
                entry['run_id'],
                entry['schedule_id'],
                entry['workflow_id'],
                entry['workflow_name'],
                entry['session_id'],
                timestamp,
                started_at,
                completed_at,
                entry.get('duration_seconds', 0),
                entry['status'],
                entry.get('result'),
                entry.get('error')
            ))
            
            if cur.rowcount > 0:
                inserted += 1
            else:
                skipped += 1
                
        except Exception as e:
            errors += 1
            print(f"❌ Error migrating entry {entry.get('run_id', 'unknown')}: {e}")
            continue
    
    conn.commit()
    cur.close()
    conn.close()
    
    print(f"\n✅ Migration complete!")
    print(f"   Inserted: {inserted}")
    print(f"   Skipped (duplicates): {skipped}")
    print(f"   Errors: {errors}")

if __name__ == "__main__":
    migrate_run_history()
