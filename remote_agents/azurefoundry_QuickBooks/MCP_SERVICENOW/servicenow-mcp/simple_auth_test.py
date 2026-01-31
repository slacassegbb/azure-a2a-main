#!/usr/bin/env python3
"""
Simple ServiceNow authentication test
"""

import requests
from requests.auth import HTTPBasicAuth
import json
from dotenv import load_dotenv
import os

def test_servicenow_auth():
    """Test ServiceNow authentication with different methods"""
    
    # Load environment variables
    load_dotenv()
    
    instance_url = os.getenv('SERVICENOW_INSTANCE_URL')
    username = os.getenv('SERVICENOW_USERNAME')
    password = os.getenv('SERVICENOW_PASSWORD')
    
    print("🔧 ServiceNow Authentication Test")
    print("=" * 50)
    print(f"Instance: {instance_url}")
    print(f"Username: {username}")
    print(f"Password: {'*' * len(password) if password else 'Not set'}")
    print()
    
    # Test 1: Basic connectivity (no auth)
    print("1️⃣ Testing basic connectivity...")
    try:
        response = requests.get(
            f"{instance_url}/api/now/table/incident?sysparm_limit=1",
            timeout=10,
            headers={"Accept": "application/json"}
        )
        print(f"   Status Code: {response.status_code}")
        print(f"   Response: {response.text[:200]}...")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print()
    
    # Test 2: Basic Authentication
    print("2️⃣ Testing Basic Authentication...")
    try:
        response = requests.get(
            f"{instance_url}/api/now/table/incident?sysparm_limit=1",
            auth=HTTPBasicAuth(username, password),
            timeout=10,
            headers={"Accept": "application/json"}
        )
        print(f"   Status Code: {response.status_code}")
        if response.status_code == 200:
            print("   ✅ Authentication successful!")
            data = response.json()
            print(f"   📊 Found {len(data.get('result', []))} incidents")
            if data.get('result'):
                incident = data['result'][0]
                print(f"   📋 Sample: {incident.get('number')} - {incident.get('short_description', 'No description')}")
        else:
            print(f"   ❌ Authentication failed")
            print(f"   Response: {response.text}")
    except requests.exceptions.Timeout:
        print("   ⏰ Request timed out - this might indicate auth is hanging")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print()
    
    # Test 3: Check if REST API is enabled
    print("3️⃣ Testing REST API availability...")
    try:
        response = requests.get(
            f"{instance_url}/api/now",
            timeout=10,
            headers={"Accept": "application/json"}
        )
        print(f"   Status Code: {response.status_code}")
        print(f"   Response: {response.text[:200]}...")
    except Exception as e:
        print(f"   ❌ Error: {e}")

if __name__ == "__main__":
    test_servicenow_auth() 