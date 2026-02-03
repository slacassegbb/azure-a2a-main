#!/usr/bin/env python3
"""
Merge agent_registry.json and agent_registry_prod.json into a unified format.
Each agent will have both local_url and production_url fields.
"""

import json
from pathlib import Path

# Read both files
data_dir = Path(__file__).parent
local_file = data_dir / "agent_registry.json"
prod_file = data_dir / "agent_registry_prod.json"

with open(local_file) as f:
    local_agents = json.load(f)

with open(prod_file) as f:
    prod_agents = json.load(f)

print(f"Loaded {len(local_agents)} local agents and {len(prod_agents)} production agents")

# Create a mapping of agent names to their data
merged_agents = {}

# Process local agents
for agent in local_agents:
    name = agent['name']
    # Get URL from the agent data
    local_url = agent.get('url', 'http://localhost:8000')  # Default if not present
    
    if name not in merged_agents:
        merged_agents[name] = agent.copy()
        merged_agents[name]['local_url'] = local_url
        merged_agents[name]['production_url'] = None
    else:
        merged_agents[name]['local_url'] = local_url

# Process production agents
for agent in prod_agents:
    name = agent['name']
    prod_url = agent.get('url', '')
    
    if name not in merged_agents:
        # Agent only in production (shouldn't happen, but handle it)
        merged_agents[name] = agent.copy()
        merged_agents[name]['local_url'] = None
        merged_agents[name]['production_url'] = prod_url
    else:
        # Update production URL
        merged_agents[name]['production_url'] = prod_url
        
        # If prod has more complete data, merge it
        if 'version' in agent and 'version' not in merged_agents[name]:
            merged_agents[name]['version'] = agent['version']

# Remove the old 'url' field and convert to list
final_agents = []
for name, agent in merged_agents.items():
    # Remove old url field if it exists
    if 'url' in agent:
        del agent['url']
    final_agents.append(agent)

# Sort by name for consistency
final_agents.sort(key=lambda x: x['name'])

# Write to new file
output_file = data_dir / "agent_registry_unified.json"
with open(output_file, 'w') as f:
    json.dump(final_agents, f, indent=2)

print(f"\n✅ Created unified registry: {output_file}")
print(f"   Total agents: {len(final_agents)}")

# Show summary
print("\n📊 Summary of merged agents:")
for agent in final_agents[:5]:
    local = agent.get('local_url', 'None')
    prod = agent.get('production_url', 'None')
    print(f"\n  {agent['name']}")
    print(f"    Local: {local}")
    print(f"    Prod:  {prod}")

if len(final_agents) > 5:
    print(f"\n  ... and {len(final_agents) - 5} more agents")

print("\n💡 Next steps:")
print("  1. Review agent_registry_unified.json")
print("  2. Update agent_registry.py to use unified format")
print("  3. Add local_url and production_url handling logic")
