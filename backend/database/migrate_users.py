#!/usr/bin/env python3
"""
Database Migration Script - Migrate Users from JSON to PostgreSQL

This script:
1. Creates the users table in PostgreSQL
2. Migrates existing users from users.json to the database
3. Validates the migration

Usage:
    python migrate_users.py
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

# Add backend to path for imports
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

# Load environment variables
ROOT_ENV_PATH = BACKEND_DIR.parent / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH, override=False)


def get_database_connection():
    """Get PostgreSQL database connection."""
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("❌ ERROR: DATABASE_URL not found in environment")
        print("💡 Make sure .env file exists with DATABASE_URL set")
        sys.exit(1)
    
    try:
        import psycopg2
        conn = psycopg2.connect(database_url)
        return conn
    except ImportError:
        print("❌ ERROR: psycopg2 not installed")
        print("💡 Run: pip install psycopg2-binary")
        sys.exit(1)
    except Exception as e:
        print(f"❌ ERROR: Failed to connect to database: {e}")
        sys.exit(1)


def create_users_table(conn):
    """Create the users table using schema.sql."""
    print("\n📋 Creating users table...")
    
    schema_file = Path(__file__).parent / "schema.sql"
    
    if not schema_file.exists():
        print(f"❌ ERROR: schema.sql not found at {schema_file}")
        sys.exit(1)
    
    with open(schema_file, 'r') as f:
        schema_sql = f.read()
    
    cursor = conn.cursor()
    try:
        cursor.execute(schema_sql)
        conn.commit()
        print("✅ Users table created successfully")
    except Exception as e:
        print(f"❌ ERROR creating table: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        cursor.close()


def load_users_from_json():
    """Load users from users.json file."""
    users_file = BACKEND_DIR / "data" / "users.json"
    
    if not users_file.exists():
        print(f"⚠️  WARNING: {users_file} not found")
        return []
    
    with open(users_file, 'r') as f:
        data = json.load(f)
        return data.get('users', [])


def migrate_users(conn, users):
    """Migrate users from JSON to PostgreSQL."""
    if not users:
        print("⚠️  No users to migrate")
        return 0
    
    print(f"\n📤 Migrating {len(users)} users to PostgreSQL...")
    
    cursor = conn.cursor()
    
    insert_sql = """
        INSERT INTO users (
            user_id, email, password_hash, name, role, 
            description, skills, color, created_at, last_login
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (user_id) DO UPDATE SET
            email = EXCLUDED.email,
            password_hash = EXCLUDED.password_hash,
            name = EXCLUDED.name,
            role = EXCLUDED.role,
            description = EXCLUDED.description,
            skills = EXCLUDED.skills,
            color = EXCLUDED.color,
            last_login = EXCLUDED.last_login
    """
    
    migrated = 0
    for user in users:
        try:
            # Convert skills list to JSON string
            skills_json = json.dumps(user.get('skills', []))
            
            # Parse datetime strings
            created_at = user.get('created_at')
            last_login = user.get('last_login')
            
            cursor.execute(insert_sql, (
                user['user_id'],
                user['email'],
                user['password_hash'],
                user['name'],
                user.get('role'),
                user.get('description', ''),
                skills_json,
                user.get('color', '#3B82F6'),
                created_at,
                last_login
            ))
            
            print(f"  ✓ Migrated user: {user['email']} ({user['user_id']})")
            migrated += 1
            
        except Exception as e:
            print(f"  ✗ Failed to migrate {user.get('email', 'unknown')}: {e}")
            conn.rollback()
            continue
    
    conn.commit()
    cursor.close()
    
    return migrated


def verify_migration(conn, expected_count):
    """Verify the migration was successful."""
    print(f"\n🔍 Verifying migration...")
    
    cursor = conn.cursor()
    
    # Count users
    cursor.execute("SELECT COUNT(*) FROM users")
    actual_count = cursor.fetchone()[0]
    
    print(f"  Expected: {expected_count} users")
    print(f"  Found:    {actual_count} users")
    
    if actual_count == expected_count:
        print("  ✅ User count matches!")
    else:
        print(f"  ⚠️  User count mismatch!")
    
    # Show sample users
    cursor.execute("SELECT user_id, email, name FROM users ORDER BY created_at LIMIT 5")
    sample_users = cursor.fetchall()
    
    print("\n📋 Sample users in database:")
    for user_id, email, name in sample_users:
        print(f"  • {name} ({email}) - {user_id}")
    
    cursor.close()


def main():
    """Main migration function."""
    print("="*60)
    print("🚀 A2A Database Migration - Users")
    print("="*60)
    
    # Get database connection
    print("\n🔌 Connecting to PostgreSQL...")
    conn = get_database_connection()
    print("✅ Connected to database")
    
    # Create table
    create_users_table(conn)
    
    # Load users from JSON
    print("\n📂 Loading users from JSON...")
    users = load_users_from_json()
    print(f"✅ Loaded {len(users)} users from users.json")
    
    # Migrate users
    migrated_count = migrate_users(conn, users)
    
    # Verify migration
    verify_migration(conn, len(users))
    
    # Close connection
    conn.close()
    
    print("\n" + "="*60)
    print(f"✅ Migration complete! {migrated_count}/{len(users)} users migrated")
    print("="*60)
    print("\n💡 Next steps:")
    print("  1. Test user authentication with PostgreSQL")
    print("  2. Update auth_service.py to use PostgreSQL")
    print("  3. Keep users.json as backup for now")


if __name__ == "__main__":
    main()
