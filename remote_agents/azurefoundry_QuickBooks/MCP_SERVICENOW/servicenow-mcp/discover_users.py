#!/usr/bin/env python3
"""
Discover working ServiceNow credentials
This script tries common default users and checks responses
"""

import requests
from requests.auth import HTTPBasicAuth
import json
from dotenv import load_dotenv
import os

def test_credentials(instance_url, username, password):
    """Test if credentials work and return detailed info"""
    
    print(f"🔍 Testing: {username}/{'*' * len(password)}")
    
    try:
        # Test basic API access
        response = requests.get(
            f"{instance_url}/api/now/table/sys_user?sysparm_limit=1",
            auth=HTTPBasicAuth(username, password),
            timeout=15,
            headers={"Accept": "application/json"}
        )
        
        print(f"   Status Code: {response.status_code}")
        
        if response.status_code == 200:
            print("   ✅ SUCCESS! This combination works")
            data = response.json()
            user_count = len(data.get('result', []))
            print(f"   📊 Found {user_count} users accessible")
            return True, data
            
        elif response.status_code == 401:
            print("   ❌ Authentication failed")
            return False, None
            
        elif response.status_code == 403:
            print("   ⚠️  Authentication succeeded but no permission to access users")
            return "partial", None
            
        else:
            print(f"   ⚠️  Unexpected status: {response.status_code}")
            print(f"   Response: {response.text[:100]}")
            return False, None
            
    except requests.exceptions.Timeout:
        print("   ⏰ Request timed out")
        return False, None
    except Exception as e:
        print(f"   ❌ Error: {str(e)[:50]}")
        return False, None

def main():
    # Load environment variables
    load_dotenv()
    
    instance_url = os.getenv('SERVICENOW_INSTANCE_URL')
    current_password = os.getenv('SERVICENOW_PASSWORD', 'Hip1hops!')
    
    print("🔧 ServiceNow Credential Discovery")
    print("=" * 50)
    print(f"Instance: {instance_url}")
    print(f"Password to try: {'*' * len(current_password)}")
    print()
    
    # List of common ServiceNow usernames to try
    common_usernames = [
        'admin',
        'administrator', 
        'system',
        'api_user',
        'service_account',
        'integration_user',
        'demo_user',
        'test_user',
        'slacasse',
        'simon',
        'simonlacasse',
        'demo.admin',
        'api.user'
    ]
    
    working_credentials = []
    
    for username in common_usernames:
        success, data = test_credentials(instance_url, username, current_password)
        if success is True:
            working_credentials.append((username, current_password))
            print(f"   🎯 WORKING CREDENTIALS FOUND: {username}")
            
            # Try to get more info about this user
            try:
                user_info_response = requests.get(
                    f"{instance_url}/api/now/table/sys_user?sysparm_query=user_name={username}&sysparm_fields=user_name,name,email,active,roles",
                    auth=HTTPBasicAuth(username, current_password),
                    timeout=10,
                    headers={"Accept": "application/json"}
                )
                if user_info_response.status_code == 200:
                    user_data = user_info_response.json()
                    if user_data.get('result'):
                        user = user_data['result'][0]
                        print(f"   👤 User: {user.get('name', 'Unknown')}")
                        print(f"   📧 Email: {user.get('email', 'None')}")
                        print(f"   ✅ Active: {user.get('active', 'Unknown')}")
            except:
                pass
                
        elif success == "partial":
            print(f"   🔓 Credentials work but limited permissions: {username}")
            
        print()
    
    print("🎯 SUMMARY")
    print("=" * 50)
    if working_credentials:
        print("✅ Working credentials found:")
        for username, password in working_credentials:
            print(f"   Username: {username}")
            print(f"   Password: {'*' * len(password)}")
            print()
        print("🔧 UPDATE YOUR .env FILE:")
        username, password = working_credentials[0]
        print(f"SERVICENOW_USERNAME={username}")
        print(f"SERVICENOW_PASSWORD={password}")
    else:
        print("❌ No working credentials found")
        print("🔧 You may need to:")
        print("   1. Create a user account in ServiceNow web interface")
        print("   2. Enable API access for your user")
        print("   3. Assign admin or API roles")

if __name__ == "__main__":
    main() 