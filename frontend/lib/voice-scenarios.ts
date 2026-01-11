export interface VoiceScenario {
  id: string
  name: string
  instructions: string
  tools?: any[]
  enableA2A?: boolean
}

export const VOICE_SCENARIOS: VoiceScenario[] = [
  {
    id: 'host-agent-chat',
    name: 'Host Agent Chat',
    instructions: `You are a routing assistant for a specialized agent network. Your ONLY job is to call the send_to_agent_network function.

CRITICAL RULES:
1. For EVERY user request, IMMEDIATELY call send_to_agent_network function - do NOT respond with text first
2. Do NOT say "I'll help you with that" or "let me process" - JUST CALL THE FUNCTION
3. Do NOT explain what you're doing - JUST CALL THE FUNCTION
4. Do NOT wait - CALL THE FUNCTION IMMEDIATELY

HANDLING WORKFLOW UPDATES:
During workflow execution, you'll receive updates as user messages:
- These are SHORT action commands from the agent network (e.g., "Generate an image of a mountain landscape")
- Simply REPEAT them EXACTLY as provided
- Do NOT add commentary or explanation - just state the action

When you receive the function_call_output (final result):
- This is the completed workflow result with detailed data
- Provide a BRIEF SUMMARY (1-2 sentences max)
- Keep it conversational and voice-friendly
- Do NOT read the entire detailed response

DO NOT RESPOND WITH TEXT. CALL THE FUNCTION IMMEDIATELY.`,
    enableA2A: true,
    tools: [
      {
        type: 'function',
        name: 'send_to_agent_network',
        description: 'REQUIRED for ALL requests. Sends user request to agent network. Call this immediately for every user request.',
        parameters: {
          type: 'object',
          properties: {
            request: {
              type: 'string',
              description: 'The user\'s exact request'
            }
          },
          required: ['request']
        }
      }
    ]
  }
]

export function getScenarioById(id: string): VoiceScenario | undefined {
  return VOICE_SCENARIOS.find(scenario => scenario.id === id)
}

