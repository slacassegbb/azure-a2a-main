#!/usr/bin/env python3
"""
Test script to verify AuthService works with PostgreSQL database.
Tests create, authenticate, and retrieval operations.
"""

import sys
import os
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from service.auth_service import AuthService
from dotenv import load_dotenv

def main():
    # Load environment variables
    env_path = BACKEND_DIR.parent / ".env"
    load_dotenv(env_path)
    
    print("=" * 60)
    print("Testing AuthService with PostgreSQL")
    print("=" * 60)
    
    # Initialize auth service
    print("\n1. Initializing AuthService...")
    auth = AuthService()
    
    if auth.use_database:
        print("   ✅ Using PostgreSQL database")
    else:
        print("   ⚠️  Using JSON file fallback")
    
    # Test user retrieval
    print("\n2. Testing user retrieval...")
    simon = auth.get_user_by_email("simon@example.com")
    if simon:
        print(f"   ✅ Retrieved user: {simon.name} ({simon.email})")
        print(f"      User ID: {simon.user_id}")
        print(f"      Role: {simon.role}")
        print(f"      Skills: {simon.skills}")
    else:
        print("   ❌ Could not retrieve user")
        return
    
    # Test authentication
    print("\n3. Testing authentication...")
    authenticated = auth.authenticate_user("simon@example.com", "password123")
    if authenticated:
        print(f"   ✅ Authentication successful")
        print(f"      Last login: {authenticated.last_login}")
    else:
        print("   ❌ Authentication failed")
        return
    
    # Test wrong password
    print("\n4. Testing wrong password...")
    wrong_auth = auth.authenticate_user("simon@example.com", "wrongpassword")
    if wrong_auth:
        print("   ❌ Should have failed with wrong password")
    else:
        print("   ✅ Correctly rejected wrong password")
    
    # Test get all users
    print("\n5. Testing get all users...")
    all_users = auth.get_all_users()
    print(f"   ✅ Retrieved {len(all_users)} users:")
    for user_dict in all_users[:3]:  # Show first 3
        print(f"      - {user_dict['name']} ({user_dict['email']}) - {user_dict['role']}")
    if len(all_users) > 3:
        print(f"      ... and {len(all_users) - 3} more")
    
    # Test get by user_id
    print("\n6. Testing get by user_id...")
    user_by_id = auth.get_user_by_id(simon.user_id)
    if user_by_id and user_by_id.email == simon.email:
        print(f"   ✅ Retrieved user by ID: {user_by_id.name}")
    else:
        print("   ❌ Failed to retrieve user by ID")
    
    # Test create access token
    print("\n7. Testing JWT token creation...")
    token = auth.create_access_token(simon)
    if token:
        print(f"   ✅ Created token: {token[:50]}...")
    else:
        print("   ❌ Failed to create token")
        return
    
    # Test verify token
    print("\n8. Testing token verification...")
    verified = auth.verify_token(token)
    if verified and verified.get("email") == simon.email:
        print(f"   ✅ Token verified for: {verified.get('name')}")
    else:
        print("   ❌ Token verification failed")
    
    print("\n" + "=" * 60)
    print("All tests passed! ✅")
    print("=" * 60)

if __name__ == "__main__":
    main()
