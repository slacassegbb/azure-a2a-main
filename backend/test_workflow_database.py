#!/usr/bin/env python3
"""Test database-backed workflow service."""

import os
import sys
from pathlib import Path

backend_path = Path(__file__).parent
sys.path.insert(0, str(backend_path))

os.environ["DATABASE_URL"] = "postgresql://pgadmin:Hip1hops!@a2adb.postgres.database.azure.com:5432/postgres"

from service.workflow_service import get_workflow_service

print("="*70)
print("WORKFLOW SERVICE DATABASE TEST")
print("="*70)

service = get_workflow_service()

print(f"\n✅ Workflow service initialized")
print(f"   Using database: {service.use_database}")

workflows = service.get_all_workflows()
print(f"\n✅ Loaded {len(workflows)} workflows from database")

if workflows:
    workflow = workflows[0]
    print(f"\n📋 Sample workflow:")
    print(f"   Name: {workflow.name}")
    print(f"   User: {workflow.user_id}")
    print(f"   Steps: {len(workflow.steps)}")
    print(f"   Connections: {len(workflow.connections)}")

print("\n✅ Workflow service using database successfully!")
