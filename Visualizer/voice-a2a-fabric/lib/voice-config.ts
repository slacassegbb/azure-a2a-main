/**
 * Voice Live Configuration
 * 
 * Centralized configuration for Voice Live API behavior and session settings
 */

export const VOICE_CONFIG = {
  // ============================================================================
  // GREETING SETTINGS
  // ============================================================================
  
  /**
   * Automatic greeting sent when user first clicks microphone button
   * Only sent once per session (tracked by hasGreetedRef)
   * Only for main Contoso Concierge voice agent
   */
  INITIAL_GREETING: "Hi there! I'm the Contoso Concierge. How can I help you today?",
  
  /**
   * Delay (in milliseconds) before sending automatic greeting
   * Allows session to be fully configured before greeting
   */
  GREETING_DELAY_MS: 500,
  
  // ============================================================================
  // VOICE LIVE API SESSION CONFIGURATION
  // ============================================================================
  
  /**
   * Default system instructions for the AI assistant
   * Used when no scenario-specific instructions are provided
   */
  DEFAULT_INSTRUCTIONS: `You are a helpful Contoso customer service assistant. Speak naturally and conversationally like a real person. Use contractions (I'm, you're, we'll) and keep your responses concise - about 2-3 sentences at a time. Listen carefully to what the customer says and respond directly to their needs. If they interrupt you, stop and address what they just said. Be warm, professional, and genuinely helpful.`,
  
  /**
   * Audio formats and sampling rates
   */
  AUDIO: {
    INPUT_FORMAT: 'pcm16',
    OUTPUT_FORMAT: 'pcm16',
    SAMPLE_RATE: 24000,
  },
  
  /**
   * Voice configuration
   */
  VOICE: {
    NAME: 'en-US-Ava:DragonHDLatestNeural',
    TYPE: 'azure-standard',
    TEMPERATURE: 0.6,
  },
  
  /**
   * Turn detection configuration (Azure Semantic VAD)
   * Controls when AI detects user has finished speaking
   */
  TURN_DETECTION: {
    TYPE: 'azure_semantic_vad',
    THRESHOLD: 0.3,
    PREFIX_PADDING_MS: 200,
    SILENCE_DURATION_MS: 200,
    REMOVE_FILLER_WORDS: false,
    INTERRUPT_RESPONSE: true,
    CREATE_RESPONSE: true,
  },
  
  /**
   * Audio processing features
   */
  AUDIO_PROCESSING: {
    NOISE_REDUCTION_TYPE: 'azure_deep_noise_suppression',
    ECHO_CANCELLATION_TYPE: 'server_echo_cancellation',
  },
  
  /**
   * Input audio transcription configuration
   * Transcription runs asynchronously with response creation
   * Useful for debugging and logging user speech
   */
  TRANSCRIPTION: {
    MODEL: 'whisper-1', // Options: whisper-1, gpt-4o-transcribe, gpt-4o-mini-transcribe, azure-speech
    LANGUAGE: undefined as string | undefined, // Optional: BCP-47 code (e.g., 'en-US') or ISO-639-1 (e.g., 'en')
    PROMPT: undefined as string | undefined, // Optional: Prompt text to guide transcription
  },
  
  /**
   * AI model temperature (0.0 - 1.0)
   * Higher = more creative, Lower = more deterministic
   */
  MODEL_TEMPERATURE: 0.6,
  
  // ============================================================================
  // BARGE-IN DETECTION SETTINGS
  // ============================================================================
  
  /**
   * Barge-in detection threshold
   * Audio level (RMS) above this value triggers interruption
   * Range: 0.0 (silence) to 1.0 (maximum)
   * Recommended: 0.02 - 0.05
   */
  BARGE_IN_THRESHOLD: 0.02,
  
  /**
   * Barge-in check interval (in milliseconds)
   * How often to check user audio levels during AI speech
   * Lower = more responsive, but more CPU usage
   */
  BARGE_IN_CHECK_INTERVAL_MS: 50,
  
  /**
   * Post-speech delay (in milliseconds)
   * Wait this long after AI starts speaking before enabling barge-in detection
   * Prevents accidental interruptions from brief pauses or background noise
   * Recommended: 300-500ms
   */
  BARGE_IN_DELAY_MS: 300,
  
  /**
   * Analyser node configuration for audio level detection
   */
  ANALYSER: {
    FFT_SIZE: 512,
    SMOOTHING_TIME_CONSTANT: 0.3,
  },
  
  // ============================================================================
  // CONVERSATION MANAGEMENT SETTINGS
  // ============================================================================
  
  /**
   * Conversation item truncation settings for barge-in
   * When user interrupts, truncate assistant audio to sync server understanding with client
   */
  CONVERSATION_TRUNCATE: {
    /**
     * Content index to truncate (always 0 for first content part)
     */
    CONTENT_INDEX: 0,
    
    /**
     * Audio offset in milliseconds to add when calculating truncation point
     * Accounts for processing delays and network latency
     * Recommended: 100-200ms
     */
    AUDIO_OFFSET_MS: 150,
  },
  
  // ============================================================================
  // AUDIO PLAYBACK SETTINGS
  // ============================================================================
  
  /**
   * Audio buffer size for initial playback
   * Number of audio chunks to buffer before starting playback
   * Higher = smoother start, but more latency
   */
  INITIAL_AUDIO_BUFFER_SIZE: 8,
  
  /**
   * Initial playback latency (in seconds)
   * Small buffer to reduce initial latency
   */
  PLAYBACK_BUFFER_SECONDS: 0.05,
  
  /**
   * Audio chunk logging interval
   * Log every Nth chunk to avoid console spam
   */
  AUDIO_LOG_INTERVAL: 50,
  
  // ============================================================================
  // A2A NETWORK SETTINGS
  // ============================================================================
  
  /**
   * A2A network call timeout (in milliseconds)
   * Pending calls older than this will be cleaned up
   * Increased to 5 minutes to handle long-running agent operations
   */
  A2A_TIMEOUT_MS: 300000, // 5 minutes
  
  /**
   * A2A cleanup check interval (in milliseconds)
   * How often to check for timed-out A2A calls
   */
  A2A_CLEANUP_INTERVAL_MS: 30000, // Check every 30 seconds
  
  // ============================================================================
  // MICROPHONE SETTINGS
  // ============================================================================
  
  /**
   * Microphone audio constraints
   */
  MICROPHONE: {
    SAMPLE_RATE: 24000,
    CHANNEL_COUNT: 1,
    ECHO_CANCELLATION: true,
    NOISE_SUPPRESSION: true,
  },
  
  /**
   * Audio processor buffer size
   * Larger = less CPU, but more latency
   */
  PROCESSOR_BUFFER_SIZE: 4096,
} as const

export type VoiceConfig = typeof VOICE_CONFIG
