# Voice Live A2A Integration - Implementation Guide

## Overview
This implementation integrates Azure Voice Live API with the A2A (Agent-to-Agent) network, enabling dynamic scenario-based voice conversations that can seamlessly interact with the backend agent network.

## Architecture

### Key Components

1. **Voice Scenarios** (`lib/voice-scenarios.ts`)
   - Defines conversational scenarios with instructions, tools, and A2A integration
   - Each scenario specifies:
     - Instructions for the AI's behavior
     - Tool definitions for function calling
     - Whether A2A network integration is enabled

2. **Enhanced Voice Live Hook** (`hooks/use-voice-live.ts`)
   - Manages WebSocket connection to Azure Voice Live API
   - Handles audio streaming (PCM16 format, 24kHz)
   - Processes function calls from the AI
   - Injects A2A network responses back into the conversation
   - Supports dynamic scenario configuration

3. **Dashboard Integration** (`components/agent-network-dashboard.tsx`)
   - Scenario selector UI
   - Bridges Voice Live with A2A network
   - Monitors A2A responses and injects them into voice conversations
   - Displays voice status (listening/speaking)

## How It Works

### Flow: Insurance Claim Scenario

1. **User starts voice conversation**
   - Selects "Insurance Claim Processing" scenario
   - Clicks microphone button
   - Voice Live connects with scenario-specific instructions and tools

2. **AI gathers information conversationally**
   - Asks about claim type, incident details, customer info
   - Natural, empathetic conversation flow
   - Validates information through dialogue

3. **AI calls `submit_claim_to_network` tool**
   - When sufficient information is collected
   - Tool call triggers `onSendToA2A` callback
   - Request is sent to backend A2A network via HTTP POST

4. **AI continues engaging the customer**
   - **CRITICAL**: AI doesn't wait silently
   - Tells customer claim is submitted
   - Provides reference number
   - Asks follow-up questions
   - Maintains conversation flow

5. **A2A network processes in background**
   - Multiple agents analyze the claim
   - Fraud detection, assessment, classification agents work
   - Dashboard shows agent activity visually

6. **Network response is injected**
   - `handleMessage` detects final response
   - Checks if it matches pending voice conversation
   - Calls `voiceLive.injectNetworkResponse()`
   - Creates function_call_output event

7. **AI communicates result**
   - Voice Live API triggers `response.create`
   - AI naturally explains the outcome
   - Provides next steps to customer
   - Closes conversation appropriately

## Scenario Structure

```typescript
export interface VoiceScenario {
  id: string
  name: string
  description: string
  instructions: string  // AI behavior prompt
  tools: VoiceTool[]    // Function definitions
  enableA2A: boolean    // Whether to integrate with A2A network
}
```

### Example: Insurance Claim Scenario

```typescript
{
  id: 'insurance-claim',
  name: 'Insurance Claim Processing',
  instructions: `
    1. Greet warmly, ask claim type
    2. Gather information conversationally
    3. When ready, use submit_claim_to_network tool
    4. CONTINUE TALKING after submitting (don't wait silently)
    5. When result arrives, share outcome naturally
    6. Keep conversation flowing - no awkward silences
  `,
  enableA2A: true,
  tools: [
    {
      name: 'submit_claim_to_network',
      description: 'Submit claim to Rogers agent network',
      parameters: {
        customer_name: string,
        claim_type: enum,
        incident_description: string,
        // ... other fields
      }
    }
  ]
}
```

## Key Features

### 1. Ultra-Smooth Audio Playback
- PCM16 audio at 24kHz
- Scheduled playback with precise timing
- 3-chunk buffer for smooth streaming
- Eliminates gaps and choppiness

### 2. Seamless A2A Integration
- Voice Live sends requests to backend
- Continues conversation while network processes
- Automatically injects responses when ready
- No interruption to conversation flow

### 3. Dynamic Scenario System
- Easy to add new scenarios
- Each scenario has custom instructions
- Tools defined per scenario
- A2A integration optional per scenario

### 4. Function Calling
- Voice Live API calls tools when appropriate
- Tools trigger backend actions
- Responses fed back to AI automatically
- AI explains results naturally to user

## Adding New Scenarios

### Example: Technical Support Scenario

```typescript
export const technicalSupportScenario: VoiceScenario = {
  id: 'technical-support',
  name: 'Technical Support',
  description: 'Help with technical issues',
  instructions: `
    You are a Rogers Technical Support specialist.
    1. Ask about the service issue
    2. Try basic troubleshooting
    3. If needed, escalate with submit_support_request tool
    4. Keep customer engaged while network processes
    5. Share specialist recommendations when available
  `,
  enableA2A: true,
  tools: [
    {
      name: 'submit_support_request',
      description: 'Escalate to technical agent network',
      parameters: {
        service_type: { enum: ['internet', 'tv', 'phone'] },
        issue_description: string,
        troubleshooting_attempted: string
      }
    }
  ]
}
```

## Technical Details

### Audio Processing
- **Input**: MediaRecorder → AudioContext → PCM16 conversion
- **Sample Rate**: 24kHz
- **Format**: 16-bit PCM (Int16Array)
- **Output**: Base64-encoded audio chunks

### WebSocket Events
- **Client Events**: 
  - `session.update` - Configure scenario
  - `input_audio_buffer.append` - Send audio
  - `conversation.item.create` - Inject responses
  - `response.create` - Trigger AI continuation

- **Server Events**:
  - `response.audio.delta` - Audio chunks
  - `response.function_call_arguments.done` - Tool call complete
  - `response.done` - Response finished

### State Management
- `isConnected` - WebSocket connection status
- `isRecording` - User speaking
- `isSpeaking` - AI speaking
- `pendingA2AResponse` - Tracking conversation ID
- `currentScenario` - Active scenario configuration

## Benefits

1. **Natural Conversation**: AI keeps talking while background processing happens
2. **Flexible Scenarios**: Easy to add new use cases
3. **Seamless Integration**: Voice Live + A2A work together transparently
4. **Professional Experience**: Ultra-smooth audio, no gaps or choppiness
5. **Extensible Architecture**: Tool system allows unlimited capabilities

## Future Enhancements

- Multi-turn complex scenarios (e.g., guided troubleshooting trees)
- Voice interruption handling (cancel A2A request if user changes mind)
- Sentiment analysis integration
- Real-time translation scenarios
- Video avatar integration for visual scenarios
- Analytics dashboard for conversation metrics
