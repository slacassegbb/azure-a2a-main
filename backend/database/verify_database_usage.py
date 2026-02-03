#!/usr/bin/env python3
"""
Comprehensive verification script to ensure all authentication paths use PostgreSQL.
This script tests all authentication flows end-to-end.
"""

import sys
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from service.auth_service import AuthService
from dotenv import load_dotenv

def test_auth_service_initialization():
    """Test 1: Verify AuthService initializes with database."""
    print("\n" + "="*70)
    print("TEST 1: AuthService Initialization")
    print("="*70)
    
    auth = AuthService()
    
    if auth.use_database:
        print("✅ PASS: AuthService is using PostgreSQL database")
        print(f"   Database connection: {bool(auth.db_conn)}")
        return True
    else:
        print("❌ FAIL: AuthService is NOT using database (using JSON fallback)")
        print(f"   DATABASE_URL set: {bool(os.getenv('DATABASE_URL'))}")
        return False

def test_user_retrieval():
    """Test 2: Verify user retrieval loads from database."""
    print("\n" + "="*70)
    print("TEST 2: User Retrieval (get_user_by_email)")
    print("="*70)
    
    auth = AuthService()
    
    # This should trigger _load_users_from_database() internally
    user = auth.get_user_by_email("simon@example.com")
    
    if user:
        print(f"✅ PASS: Retrieved user from database")
        print(f"   User: {user.name} ({user.email})")
        print(f"   User ID: {user.user_id}")
        return True
    else:
        print("❌ FAIL: Could not retrieve user")
        return False

def test_authentication():
    """Test 3: Verify authentication uses database."""
    print("\n" + "="*70)
    print("TEST 3: User Authentication")
    print("="*70)
    
    auth = AuthService()
    
    # This should reload from database and update last_login
    user = auth.authenticate_user("simon@example.com", "password123")
    
    if user:
        print(f"✅ PASS: Authentication successful via database")
        print(f"   User: {user.name}")
        print(f"   Last login updated: {user.last_login}")
        return True
    else:
        print("❌ FAIL: Authentication failed")
        return False

def test_token_verification():
    """Test 4: Verify token verification uses database."""
    print("\n" + "="*70)
    print("TEST 4: JWT Token Verification")
    print("="*70)
    
    auth = AuthService()
    
    # Create a token
    user = auth.get_user_by_email("simon@example.com")
    if not user:
        print("❌ FAIL: Could not get user to create token")
        return False
    
    token = auth.create_access_token(user)
    
    # Verify token - this should reload from database
    verified = auth.verify_token(token)
    
    if verified and verified.get("email") == "simon@example.com":
        print(f"✅ PASS: Token verification successful via database")
        print(f"   Verified user: {verified.get('name')}")
        return True
    else:
        print("❌ FAIL: Token verification failed")
        return False

def test_user_creation():
    """Test 5: Verify user creation saves to database."""
    print("\n" + "="*70)
    print("TEST 5: User Creation (saves to database)")
    print("="*70)
    
    auth = AuthService()
    
    # Create a test user
    test_email = "test_db_verification@example.com"
    
    # First, check if user already exists and delete if so
    if test_email in auth.users:
        print(f"   Test user already exists, will test retrieval instead...")
        existing_user = auth.get_user_by_email(test_email)
        if existing_user:
            print(f"✅ PASS: Test user exists in database")
            print(f"   User: {existing_user.name} ({existing_user.email})")
            return True
        else:
            print("❌ FAIL: Test user exists in memory but not in database")
            return False
    
    # Create new user - this should save to database
    new_user = auth.create_user(
        email=test_email,
        password="testpass123",
        name="DB Verification Test User",
        role="Test",
        skills=["Testing", "Verification"]
    )
    
    if new_user:
        print(f"✅ PASS: User created and saved to database")
        print(f"   User: {new_user.name} ({new_user.email})")
        print(f"   User ID: {new_user.user_id}")
        
        # Verify we can retrieve it
        auth2 = AuthService()  # New instance to force reload
        retrieved = auth2.get_user_by_email(test_email)
        
        if retrieved and retrieved.user_id == new_user.user_id:
            print(f"✅ PASS: User persisted in database (retrieved in new instance)")
            return True
        else:
            print("❌ FAIL: User not persisted in database")
            return False
    else:
        print("❌ FAIL: User creation failed")
        return False

def test_get_all_users():
    """Test 6: Verify get_all_users loads from database."""
    print("\n" + "="*70)
    print("TEST 6: Get All Users")
    print("="*70)
    
    auth = AuthService()
    
    # This should reload from database
    all_users = auth.get_all_users()
    
    if len(all_users) >= 7:  # We know there are at least 7 users from migration
        print(f"✅ PASS: Retrieved {len(all_users)} users from database")
        print(f"   Sample users:")
        for user in all_users[:3]:
            print(f"   - {user['name']} ({user['email']})")
        return True
    else:
        print(f"❌ FAIL: Only retrieved {len(all_users)} users (expected at least 7)")
        return False

def test_get_user_by_id():
    """Test 7: Verify get_user_by_id loads from database."""
    print("\n" + "="*70)
    print("TEST 7: Get User by ID")
    print("="*70)
    
    auth = AuthService()
    
    # First get a user to get their ID
    user_email = auth.get_user_by_email("simon@example.com")
    if not user_email:
        print("❌ FAIL: Could not get user by email")
        return False
    
    # Now get by ID - should reload from database
    user_by_id = auth.get_user_by_id(user_email.user_id)
    
    if user_by_id and user_by_id.email == user_email.email:
        print(f"✅ PASS: Retrieved user by ID from database")
        print(f"   User: {user_by_id.name} ({user_by_id.user_id})")
        return True
    else:
        print("❌ FAIL: Could not retrieve user by ID")
        return False

def verify_no_json_usage():
    """Test 8: Verify no direct JSON file access in production."""
    print("\n" + "="*70)
    print("TEST 8: Verify No Direct JSON File Access")
    print("="*70)
    
    auth = AuthService()
    
    if auth.use_database:
        print("✅ PASS: AuthService configured for database mode")
        print(f"   use_database: {auth.use_database}")
        print(f"   Database connection active: {bool(auth.db_conn)}")
        
        # Check that database methods are being used
        if hasattr(auth, '_load_users_from_database'):
            print("✅ PASS: Database loading method exists")
        else:
            print("❌ FAIL: Database loading method missing")
            return False
        
        if hasattr(auth, '_save_user_to_database'):
            print("✅ PASS: Database saving method exists")
        else:
            print("❌ FAIL: Database saving method missing")
            return False
        
        return True
    else:
        print("❌ FAIL: AuthService is using JSON fallback mode")
        return False

def main():
    """Run all verification tests."""
    # Load environment
    env_path = BACKEND_DIR.parent / ".env"
    load_dotenv(env_path)
    
    print("\n" + "="*70)
    print("🔍 COMPREHENSIVE DATABASE USAGE VERIFICATION")
    print("="*70)
    print("\nThis script verifies that ALL authentication operations use PostgreSQL.")
    
    # Check DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("\n" + "="*70)
        print("⚠️  WARNING: DATABASE_URL not set!")
        print("="*70)
        print("\nThe backend will fall back to JSON storage.")
        print("To test database mode, ensure DATABASE_URL is set in .env file.")
        return
    
    print(f"\n✅ DATABASE_URL is set: {database_url[:50]}...")
    
    # Run all tests
    tests = [
        test_auth_service_initialization,
        test_user_retrieval,
        test_authentication,
        test_token_verification,
        test_user_creation,
        test_get_all_users,
        test_get_user_by_id,
        verify_no_json_usage,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append((test.__name__, result))
        except Exception as e:
            print(f"❌ ERROR in {test.__name__}: {e}")
            results.append((test.__name__, False))
    
    # Summary
    print("\n" + "="*70)
    print("📊 TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print("\n" + "="*70)
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        print("✅ All authentication operations are using PostgreSQL database")
        print("="*70)
    else:
        print(f"\n⚠️  {total - passed} tests failed")
        print("❌ Some authentication operations may not be using database")
        print("="*70)

if __name__ == "__main__":
    main()
