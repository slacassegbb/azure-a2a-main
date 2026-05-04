#!/usr/bin/env python3

import sys
sys.path.append('/Users/simonlacasse/Downloads/sl-a2a-main2/remote_agents/azurefoundry_gardening')

def test_visual_intelligence():
    """Test how the agent handles visual analysis with the updated prompt."""
    
    try:
        from foundry_agent import FoundryGardeningAgent
        agent = FoundryGardeningAgent()
        system_prompt = agent._get_agent_instructions()
        
        print("📋 UPDATED PROMPT ANALYSIS:")
        print(f"Prompt length: {len(system_prompt)} characters")
        
        # Check key improvements
        improvements = {
            "ANALYZE WHAT YOU SEE": "visual analysis instructions",
            "Trust your gardening expertise": "flexible decision-making guidance", 
            "rigid thresholds": "intelligent over hardcoded responses",
            "Make decisions based on visual observations": "observation-based logic",
            "what you observe in the photo": "photo-based irrigation decisions"
        }
        
        for key, description in improvements.items():
            if key in system_prompt:
                print(f"✅ Contains {description}")
            else:
                print(f"❌ Missing {description}")
                
        print("\n🔍 VISUAL INTELLIGENCE SECTIONS:")
        lines = system_prompt.split('\n')
        for line in lines:
            if any(word in line.lower() for word in ['analyze', 'visual', 'observe', 'photo', 'see']):
                if line.strip():
                    print(f"→ {line.strip()}")
                    
        print(f"\n📊 KEY PROMPT IMPROVEMENTS:")
        print(f"- Prioritizes visual intelligence: {'✅' if 'ANALYZE WHAT YOU SEE' in system_prompt else '❌'}")
        print(f"- Encourages expertise-based decisions: {'✅' if 'Trust your gardening expertise' in system_prompt else '❌'}")
        print(f"- Flexible irrigation logic: {'✅' if 'what you observe in the photo' in system_prompt else '❌'}")
        print(f"- Maintains tool calling enforcement: {'✅' if 'EVERY RUN, no exceptions' in system_prompt else '❌'}")
        
        # Test visual intelligence with a mock scenario
        print(f"\n🧪 MOCK VISUAL ANALYSIS TEST:")
        print("Scenario: Dry topsoil visible in photo during germination")
        print("Expected: Agent should recognize need to irrigate based on visual evidence")
        print("Old approach: Would follow rigid '20% water threshold' rule")
        print("New approach: Should analyze photo and make expert gardening decision")
        
        if "what you observe in the photo" in system_prompt and "Trust your gardening expertise" in system_prompt:
            print("✅ NEW APPROACH: Agent should now use visual intelligence!")
        else:
            print("❌ Still using rigid rules approach")
        
    except Exception as e:
        print(f"Error loading agent: {e}")

if __name__ == "__main__":
    test_visual_intelligence()