#!/usr/bin/env python3
"""
Check and display agent URLs from the database for Stripe and Twilio agents.
This helps diagnose scheduled workflow connection issues.
"""

import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
ROOT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH, override=False)

# Try to get DATABASE_URL
database_url = os.environ.get('DATABASE_URL')

if not database_url:
    print("❌ DATABASE_URL not found in environment")
    print("Please set it in your .env file or environment")
    exit(1)

print(f"✅ Found DATABASE_URL")
print(f"🔍 Checking Stripe and Twilio agent URLs in database...\n")

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    conn = psycopg2.connect(database_url)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT name, local_url, production_url 
        FROM agents 
        WHERE name IN ('AI Foundry Stripe Agent', 'Twilio SMS Agent')
        ORDER BY name
    """)
    
    agents = cur.fetchall()
    
    if not agents:
        print("⚠️  No Stripe or Twilio agents found in database")
    else:
        for agent in agents:
            print(f"📋 {agent['name']}")
            print(f"   Local URL:      {agent['local_url'] or '(not set)'}")
            print(f"   Production URL: {agent['production_url'] or '(not set)'}")
            print()
            
            # Check if production URL is set
            if not agent['production_url']:
                print(f"   ⚠️  WARNING: No production URL set for {agent['name']}")
                print(f"   Scheduled workflows will fail if trying to use this agent!")
                print()
    
    cur.close()
    conn.close()
    
    print("\n" + "="*60)
    print("💡 TIP: Scheduled workflows always try to use production_url")
    print("   If production_url is not set, they fall back to local_url")
    print("   Make sure your agents are deployed to Azure and have")
    print("   their production URLs properly configured in the database.")
    
except Exception as e:
    print(f"❌ Error querying database: {e}")
    import traceback
    traceback.print_exc()
