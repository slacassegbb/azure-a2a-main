#!/usr/bin/env python3
"""Migrate agent files registry from JSON to PostgreSQL."""

import os
import sys
import json
from pathlib import Path
import psycopg2
from datetime import datetime

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://pgadmin:Hip1hops!@a2adb.postgres.database.azure.com:5432/postgres')

def migrate_agent_files():
    """Migrate agent files from JSON file to PostgreSQL."""
    
    # Load existing agent files registry
    registry_file = Path(__file__).parent.parent / 'data' / 'agent_files_registry.json'
    
    if not registry_file.exists():
        print(f"❌ Agent files registry not found: {registry_file}")
        return
    
    with open(registry_file, 'r') as f:
        registry = json.load(f)
    
    # Count total files
    total_files = sum(len(files) for files in registry.values())
    print(f"📊 Found {total_files} files across {len(registry)} sessions")
    
    # Connect to database
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    inserted = 0
    skipped = 0
    errors = 0
    
    for session_id, files in registry.items():
        for file_entry in files:
            try:
                # Parse datetime string
                uploaded_at = file_entry.get('uploadedAt')
                if isinstance(uploaded_at, str):
                    uploaded_at = datetime.fromisoformat(uploaded_at.replace('Z', '+00:00'))
                
                # Insert into database (using ON CONFLICT to skip duplicates)
                cur.execute("""
                    INSERT INTO agent_files (
                        id,
                        session_id,
                        filename,
                        original_name,
                        size,
                        content_type,
                        uploaded_at,
                        uri,
                        source_agent,
                        file_type
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (id) DO NOTHING
                """, (
                    file_entry['id'],
                    session_id,
                    file_entry['filename'],
                    file_entry.get('originalName', file_entry['filename']),
                    file_entry.get('size', 0),
                    file_entry.get('contentType', 'application/octet-stream'),
                    uploaded_at,
                    file_entry['uri'],
                    file_entry.get('sourceAgent'),
                    file_entry.get('type', 'agent_generated')
                ))
                
                if cur.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
                    
            except Exception as e:
                errors += 1
                print(f"❌ Error migrating file {file_entry.get('id', 'unknown')}: {e}")
                continue
    
    conn.commit()
    cur.close()
    conn.close()
    
    print(f"\n✅ Migration complete!")
    print(f"   Inserted: {inserted}")
    print(f"   Skipped (duplicates): {skipped}")
    print(f"   Errors: {errors}")
    print(f"\n📊 Sessions migrated: {len(registry)}")

if __name__ == "__main__":
    migrate_agent_files()
