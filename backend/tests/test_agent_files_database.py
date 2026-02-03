#!/usr/bin/env python3
"""Test agent files registry database operations."""
import os
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Set DATABASE_URL before importing
os.environ["DATABASE_URL"] = "postgresql://pgadmin:Hip1hops!@a2adb.postgres.database.azure.com:5432/postgres"

# Import after setting DATABASE_URL
import service.agent_file_registry as registry

def test_agent_files_database():
    """Test agent files registry with database operations."""
    print("\n🧪 Testing Agent Files Registry Database Operations\n")
    print("=" * 60)
    
    print(f"✓ Registry initialized (use_database={registry._use_database})")
    
    # Test 1: Get files for a session
    print("\n📁 Test 1: Getting files for existing session...")
    test_session = "sess_2f207f9d-e50a-40c2-a55f-092465ad3160"
    files = registry.get_agent_files(test_session)
    print(f"✓ Retrieved {len(files)} files for session")
    if files:
        first_file = files[0]
        print(f"  Sample file:")
        print(f"    - filename: {first_file.get('filename')}")
        print(f"    - sourceAgent: {first_file.get('sourceAgent')}")
        print(f"    - contentType: {first_file.get('contentType')}")
        print(f"    - uploadedAt: {first_file.get('uploadedAt')}")
    
    # Test 2: Get all sessions
    print("\n👥 Test 2: Getting all sessions with files...")
    sessions = registry.get_all_sessions()
    print(f"✓ Found {len(sessions)} sessions with files")
    if sessions:
        print(f"  Sample sessions: {sessions[:3]}")
    
    # Test 3: Register a new file
    print("\n➕ Test 3: Registering a new test file...")
    test_file = registry.register_agent_file(
        session_id="test-session-123",
        uri="https://test.blob.core.windows.net/test/image.png?token=abc123",
        filename="test_image.png",
        content_type="image/png",
        size=1024,
        source_agent="Test Agent"
    )
    print(f"✓ Registered file: {test_file['id']}")
    print(f"  - filename: {test_file['filename']}")
    print(f"  - size: {test_file['size']} bytes")
    
    # Test 4: Verify file was saved
    print("\n✅ Test 4: Verifying file was saved to database...")
    files_for_test_session = registry.get_agent_files("test-session-123")
    found = any(f['id'] == test_file['id'] for f in files_for_test_session)
    if found:
        print(f"✓ File {test_file['id']} found in database")
    else:
        print(f"❌ File {test_file['id']} NOT found in database")
    
    # Test 5: Register duplicate (should return existing)
    print("\n🔄 Test 5: Testing duplicate detection...")
    duplicate = registry.register_agent_file(
        session_id="test-session-123",
        uri="https://test.blob.core.windows.net/test/image.png?token=xyz789",
        filename="test_image_duplicate.png",
        content_type="image/png",
        size=2048,
        source_agent="Test Agent"
    )
    if duplicate['id'] == test_file['id']:
        print(f"✓ Duplicate detection working - returned existing file")
    else:
        print(f"❌ Duplicate detection failed - created new file")
    
    print("\n" + "=" * 60)
    print("✅ All agent files database tests completed!\n")
    return True

if __name__ == "__main__":
    try:
        success = test_agent_files_database()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
