#!/usr/bin/env python3
"""Migrate scheduled workflows from JSON to PostgreSQL database."""

import json
import psycopg2
from pathlib import Path
from datetime import datetime

DATABASE_URL = "postgresql://pgadmin:Hip1hops!@a2adb.postgres.database.azure.com:5432/postgres"

print('='*70)
print('SCHEDULED WORKFLOW MIGRATION: JSON → PostgreSQL')
print('='*70)

json_file = Path(__file__).parent.parent / 'data' / 'scheduled_workflows.json'
print(f'\nLoading scheduled workflows from: {json_file.name}')

with open(json_file, 'r') as f:
    schedules = json.load(f)

print(f'✅ Loaded {len(schedules)} scheduled workflows from JSON')

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

cur.execute('DELETE FROM scheduled_workflows')
print(f'\n🗑️  Cleared existing scheduled workflows from database')

inserted = 0
for schedule in schedules:
    try:
        # Parse datetime strings
        created_at = schedule.get('created_at')
        updated_at = schedule.get('updated_at')
        last_run = schedule.get('last_run')
        next_run = schedule.get('next_run')
        run_at = schedule.get('run_at')
        
        cur.execute("""
            INSERT INTO scheduled_workflows (
                id, workflow_id, workflow_name, session_id, schedule_type,
                enabled, created_at, updated_at, last_run, next_run, run_count,
                last_status, last_error, success_count, failure_count,
                run_at, interval_minutes, time_of_day, days_of_week, day_of_month,
                cron_expression, timezone, timeout, retry_on_failure, max_retries, max_runs,
                description, tags, workflow_goal
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s::jsonb, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s::jsonb, %s
            )
        """, (
            schedule.get('id'),
            schedule.get('workflow_id'),
            schedule.get('workflow_name'),
            schedule.get('session_id'),
            schedule.get('schedule_type'),
            schedule.get('enabled', True),
            created_at,
            updated_at,
            last_run,
            next_run,
            schedule.get('run_count', 0),
            schedule.get('last_status'),
            schedule.get('last_error'),
            schedule.get('success_count', 0),
            schedule.get('failure_count', 0),
            run_at,
            schedule.get('interval_minutes'),
            schedule.get('time_of_day'),
            json.dumps(schedule.get('days_of_week')) if schedule.get('days_of_week') else None,
            schedule.get('day_of_month'),
            schedule.get('cron_expression'),
            schedule.get('timezone', 'UTC'),
            schedule.get('timeout', 300),
            schedule.get('retry_on_failure', False),
            schedule.get('max_retries', 3),
            schedule.get('max_runs'),
            schedule.get('description'),
            json.dumps(schedule.get('tags', [])),
            schedule.get('workflow_goal')
        ))
        inserted += 1
        print(f'  ✓ Migrated: {schedule.get("workflow_name")} ({schedule.get("schedule_type")})')
    except Exception as e:
        print(f'  ✗ Failed: {schedule.get("workflow_name")} - {e}')

conn.commit()

cur.execute('SELECT COUNT(*) FROM scheduled_workflows')
count = cur.fetchone()[0]

print(f'\n{"="*70}')
print(f'✅ Migration complete!')
print(f'   - Inserted: {inserted} scheduled workflows')
print(f'   - Database count: {count} scheduled workflows')

cur.execute("""
    SELECT id, workflow_name, schedule_type, enabled
    FROM scheduled_workflows 
    ORDER BY created_at DESC
    LIMIT 5
""")

print(f'\n📋 Sample scheduled workflows in database:')
for wf_id, name, sched_type, enabled in cur.fetchall():
    status = "✓ enabled" if enabled else "✗ disabled"
    print(f'   - {name} ({sched_type}) {status}')

cur.close()
conn.close()

print(f'\n✅ Scheduled workflows now stored in PostgreSQL database!')
print('='*70)
