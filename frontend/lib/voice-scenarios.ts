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
5. After receiving the function result, provide a BRIEF SUMMARY (1-2 sentences max) of the key findings

Examples of requests that REQUIRE send_to_agent_network (call it, don't talk about it):
- "use the branding agent" → CALL FUNCTION NOW
- "find company branding" → CALL FUNCTION NOW
- "generate an image" → CALL FUNCTION NOW
- "analyze this data" → CALL FUNCTION NOW
- "search for information" → CALL FUNCTION NOW
- ANY other request → CALL FUNCTION NOW

RESPONSE RULES:
- Keep responses SHORT and conversational (voice-friendly)
- Summarize the main points only
- Do NOT read the entire detailed response
- Example: "I found the branding guidelines. The primary colors are blue and white, and the logo should be used with proper spacing."

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

