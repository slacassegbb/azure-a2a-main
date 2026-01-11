#!/usr/bin/env python3
"""
Check if environment variables are loading correctly
"""

import os
from dotenv import load_dotenv

def check_environment():
    print("Checking environment variables...")
    print("=" * 50)
    
    # Load .env file
    load_dotenv()
    
    # Check required variables
    required_vars = [
        'SERVICENOW_INSTANCE_URL',
        'SERVICENOW_USERNAME', 
        'SERVICENOW_PASSWORD'
    ]
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Hide password for security
            if 'PASSWORD' in var:
                display_value = '*' * len(value)
            else:
                display_value = value
            print(f"✅ {var}: {display_value}")
        else:
            print(f"❌ {var}: NOT SET")
    
    print("\n" + "=" * 50)
    
    # Test basic connection
    if all(os.getenv(var) for var in required_vars):
        print("All required variables are set!")
        
        # Test ServiceNow connection
        import requests
        
        instance_url = os.getenv('SERVICENOW_INSTANCE_URL')
        username = os.getenv('SERVICENOW_USERNAME')
        password = os.getenv('SERVICENOW_PASSWORD')
        
        print(f"\nTesting connection to: {instance_url}")
        
        try:
            # Test basic auth with a simple API call
            auth = (username, password)
            url = f"{instance_url}/api/now/table/sys_user?sysparm_limit=1"
            
            response = requests.get(url, auth=auth, timeout=10)
            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 200:
                print("✅ Authentication successful!")
                data = response.json()
                print(f"✅ Retrieved {len(data.get('result', []))} user records")
            elif response.status_code == 401:
                print("❌ Authentication failed - Check your username/password")
            elif response.status_code == 403:
                print("❌ Access denied - Your account may not have API permissions")
            else:
                print(f"⚠️  Unexpected response: {response.status_code}")
                print(f"Response: {response.text[:200]}...")
                
        except requests.exceptions.ConnectionError:
            print("❌ Connection failed - Check your instance URL")
        except Exception as e:
            print(f"❌ Error: {e}")
    else:
        print("❌ Missing required environment variables")

if __name__ == "__main__":
    check_environment() 