"""
Script to update the test77 workflow with clearer step descriptions
to prevent agent confusion between bills and invoices.
"""

import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor

# New step descriptions - match by agent name and step index
NEW_STEPS = [
    {
        "index": 0,
        "agentMatch": "Email",
        "description": "Search for emails from Ryan and download the latest invoice PDF. Extract all invoice data including vendor name, invoice number, line items with descriptions and amounts, and total."
    },
    {
        "index": 1,
        "agentMatch": "Teams",
        "description": "APPROVAL REQUIRED: Send a Teams message asking for approval. Include the vendor name, invoice total, and line items. Ask: 'Should I record this vendor payable in QuickBooks?' Wait for 'approve' or 'reject'."
    },
    {
        "index": 2,
        "agentMatch": "QuickBooks",
        "description": "Record the vendor payable in QuickBooks. This is money WE OWE to the vendor (not money owed to us). Use the vendor name and line items from Step 1."
    },
    {
        "index": 3,
        "agentMatch": "QuickBooks",
        "description": "Ask the user: 'Which customer should I bill for this work?' After getting the customer name, create a customer invoice in QuickBooks. This is money the CUSTOMER OWES US for our services."
    },
    {
        "index": 4,
        "agentMatch": "Stripe",
        "description": "Send a Stripe invoice to the same customer. Search for them by name, create an invoice with the same amounts, and send it."
    },
]

def main():
    import sys
    sys.stdout.flush()
    
    database_url = os.environ.get('DATABASE_URL')
    print(f"Checking DATABASE_URL: {'set' if database_url else 'not set'}", flush=True)
    
    if not database_url:
        print("❌ DATABASE_URL environment variable not set", flush=True)
        print("Please set it and try again.", flush=True)
        return
    
    try:
        conn = psycopg2.connect(database_url)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Find the test77 workflow
        cur.execute("""
            SELECT id, name, description, steps
            FROM workflows
            WHERE name ILIKE '%test77%' OR name ILIKE '%test 77%'
            ORDER BY created_at DESC
            LIMIT 10
        """)
        
        workflows = cur.fetchall()
        
        if not workflows:
            # Try to find workflows with similar content
            print("No workflow named 'test77' found. Searching for workflows with 'Ryan' or 'vendor payable'...")
            cur.execute("""
                SELECT id, name, description, steps
                FROM workflows
                WHERE steps::text ILIKE '%ryan%' 
                   OR steps::text ILIKE '%vendor%'
                   OR steps::text ILIKE '%bill%'
                ORDER BY created_at DESC
                LIMIT 10
            """)
            workflows = cur.fetchall()
        
        if not workflows:
            print("❌ No matching workflows found.")
            print("\nListing all workflows:")
            cur.execute("SELECT id, name FROM workflows ORDER BY created_at DESC LIMIT 20")
            all_workflows = cur.fetchall()
            for wf in all_workflows:
                print(f"  - {wf['name']} (id: {wf['id']})")
            cur.close()
            conn.close()
            return
        
        print(f"\n✅ Found {len(workflows)} matching workflow(s):\n")
        
        for i, wf in enumerate(workflows):
            print(f"{i+1}. {wf['name']} (id: {wf['id']})")
            steps = wf['steps']
            if steps:
                print(f"   Steps ({len(steps)}):")
                for step in steps:
                    order = step.get('order', '?')
                    agent = step.get('agentName', 'Unknown')
                    desc = step.get('description', '')[:80]
                    print(f"     {order}: [{agent}] {desc}...")
            print()
        
        # Ask which workflow to update
        if len(workflows) == 1:
            selected = workflows[0]
            print(f"Updating workflow: {selected['name']}")
        else:
            choice = input("Enter the number of the workflow to update (or 'q' to quit): ").strip()
            if choice.lower() == 'q':
                cur.close()
                conn.close()
                return
            selected = workflows[int(choice) - 1]
        
        # Update the steps - match by index position in the array and fix order numbers
        steps = selected['steps']
        updated_count = 0
        
        # Sort steps by current order to get consistent ordering
        steps.sort(key=lambda x: (x.get('order', 0), x.get('id', '')))
        
        for i, step in enumerate(steps):
            if i < len(NEW_STEPS):
                new_step = NEW_STEPS[i]
                agent_name = step.get('agentName', '')
                
                # Verify agent matches (sanity check)
                if new_step['agentMatch'].lower() in agent_name.lower():
                    old_desc = step.get('description', '')
                    new_desc = new_step['description']
                    
                    # Fix the order number
                    step['order'] = i
                    
                    if old_desc != new_desc:
                        print(f"\n📝 Updating step {i} ({agent_name}):", flush=True)
                        print(f"   OLD: {old_desc[:60]}...", flush=True)
                        print(f"   NEW: {new_desc[:60]}...", flush=True)
                        step['description'] = new_desc
                        updated_count += 1
                else:
                    print(f"\n⚠️  Step {i}: Agent mismatch - expected '{new_step['agentMatch']}', got '{agent_name}'", flush=True)
        
        if updated_count == 0:
            print("\n⚠️  No steps were updated (already up to date or no matches)", flush=True)
            cur.close()
            conn.close()
            return
        
        # Save the updated workflow
        cur.execute("""
            UPDATE workflows
            SET steps = %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
        """, (json.dumps(steps), selected['id']))
        
        conn.commit()
        print(f"\n✅ Successfully updated {updated_count} steps in workflow '{selected['name']}'", flush=True)
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        raise

if __name__ == "__main__":
    main()