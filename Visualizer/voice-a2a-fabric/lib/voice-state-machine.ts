/**
 * Voice State Machine for managing voice conversation lifecycle.
 * 
 * This provides a clean, predictable state management system for voice interactions,
 * replacing scattered boolean flags with a proper state machine.
 */

/**
 * Voice conversation states
 */
export enum VoiceState {
  DISCONNECTED = 'DISCONNECTED',     // No connection
  CONNECTING = 'CONNECTING',         // Attempting to connect
  CONNECTED = 'CONNECTED',           // Connected but not recording
  RECORDING = 'RECORDING',           // Recording user audio
  SPEAKING = 'SPEAKING',             // AI is speaking
  PAUSED = 'PAUSED',                 // Temporarily paused
  RECONNECTING = 'RECONNECTING',     // Attempting to reconnect
  ERROR = 'ERROR',                   // Error state
}

/**
 * Voice state transitions (what actions can happen in each state)
 */
export const VoiceStateTransitions: Record<VoiceState, VoiceState[]> = {
  [VoiceState.DISCONNECTED]: [VoiceState.CONNECTING],
  [VoiceState.CONNECTING]: [VoiceState.CONNECTED, VoiceState.ERROR, VoiceState.DISCONNECTED],
  [VoiceState.CONNECTED]: [VoiceState.RECORDING, VoiceState.DISCONNECTED, VoiceState.ERROR],
  [VoiceState.RECORDING]: [VoiceState.SPEAKING, VoiceState.PAUSED, VoiceState.CONNECTED, VoiceState.DISCONNECTED, VoiceState.ERROR, VoiceState.RECONNECTING],
  [VoiceState.SPEAKING]: [VoiceState.RECORDING, VoiceState.CONNECTED, VoiceState.DISCONNECTED, VoiceState.ERROR, VoiceState.RECONNECTING],
  [VoiceState.PAUSED]: [VoiceState.RECORDING, VoiceState.CONNECTED, VoiceState.DISCONNECTED, VoiceState.ERROR],
  [VoiceState.RECONNECTING]: [VoiceState.CONNECTED, VoiceState.DISCONNECTED, VoiceState.ERROR],
  [VoiceState.ERROR]: [VoiceState.DISCONNECTED, VoiceState.RECONNECTING],
};

/**
 * State machine class for voice conversation
 */
export class VoiceStateMachine {
  private currentState: VoiceState;
  private previousState: VoiceState | null = null;
  private stateHistory: VoiceState[] = [];
  private maxHistorySize = 10;
  private listeners: Set<(state: VoiceState, previousState: VoiceState | null) => void> = new Set();

  constructor(initialState: VoiceState = VoiceState.DISCONNECTED) {
    this.currentState = initialState;
    this.stateHistory.push(initialState);
  }

  /**
   * Get current state
   */
  getState(): VoiceState {
    return this.currentState;
  }

  /**
   * Get previous state
   */
  getPreviousState(): VoiceState | null {
    return this.previousState;
  }

  /**
   * Get state history
   */
  getHistory(): VoiceState[] {
    return [...this.stateHistory];
  }

  /**
   * Check if transition is valid
   */
  canTransitionTo(newState: VoiceState): boolean {
    const allowedTransitions = VoiceStateTransitions[this.currentState];
    return allowedTransitions.includes(newState);
  }

  /**
   * Transition to a new state
   * @throws Error if transition is invalid
   */
  transitionTo(newState: VoiceState, force: boolean = false): void {
    if (this.currentState === newState) {
      console.warn(`[VoiceStateMachine] Already in state ${newState}`);
      return;
    }

    if (!force && !this.canTransitionTo(newState)) {
      console.error(
        `[VoiceStateMachine] Invalid transition from ${this.currentState} to ${newState}`,
        `Allowed: ${VoiceStateTransitions[this.currentState].join(', ')}`
      );
      throw new Error(`Invalid state transition: ${this.currentState} → ${newState}`);
    }

    console.log(`[VoiceStateMachine] ${this.currentState} → ${newState}`);
    
    this.previousState = this.currentState;
    this.currentState = newState;
    
    // Update history
    this.stateHistory.push(newState);
    if (this.stateHistory.length > this.maxHistorySize) {
      this.stateHistory.shift();
    }

    // Notify listeners
    this.notifyListeners();
  }

  /**
   * Subscribe to state changes
   */
  subscribe(listener: (state: VoiceState, previousState: VoiceState | null) => void): () => void {
    this.listeners.add(listener);
    
    // Return unsubscribe function
    return () => {
      this.listeners.delete(listener);
    };
  }

  /**
   * Notify all listeners of state change
   */
  private notifyListeners(): void {
    this.listeners.forEach(listener => {
      try {
        listener(this.currentState, this.previousState);
      } catch (err) {
        console.error('[VoiceStateMachine] Error in listener:', err);
      }
    });
  }

  /**
   * State check helpers
   */
  isDisconnected(): boolean {
    return this.currentState === VoiceState.DISCONNECTED;
  }

  isConnecting(): boolean {
    return this.currentState === VoiceState.CONNECTING;
  }

  isConnected(): boolean {
    return this.currentState === VoiceState.CONNECTED ||
           this.currentState === VoiceState.RECORDING ||
           this.currentState === VoiceState.SPEAKING ||
           this.currentState === VoiceState.PAUSED;
  }

  isRecording(): boolean {
    return this.currentState === VoiceState.RECORDING;
  }

  isSpeaking(): boolean {
    return this.currentState === VoiceState.SPEAKING;
  }

  isPaused(): boolean {
    return this.currentState === VoiceState.PAUSED;
  }

  isReconnecting(): boolean {
    return this.currentState === VoiceState.RECONNECTING;
  }

  isError(): boolean {
    return this.currentState === VoiceState.ERROR;
  }

  /**
   * Reset to initial state
   */
  reset(): void {
    this.previousState = this.currentState;
    this.currentState = VoiceState.DISCONNECTED;
    this.stateHistory = [VoiceState.DISCONNECTED];
    this.notifyListeners();
  }

  /**
   * Get state description
   */
  getStateDescription(): string {
    const descriptions: Record<VoiceState, string> = {
      [VoiceState.DISCONNECTED]: 'Not connected',
      [VoiceState.CONNECTING]: 'Connecting to voice service...',
      [VoiceState.CONNECTED]: 'Connected and ready',
      [VoiceState.RECORDING]: 'Listening to you',
      [VoiceState.SPEAKING]: 'AI is speaking',
      [VoiceState.PAUSED]: 'Paused',
      [VoiceState.RECONNECTING]: 'Reconnecting...',
      [VoiceState.ERROR]: 'Connection error',
    };
    return descriptions[this.currentState];
  }
}

/**
 * Create a new voice state machine instance
 */
export function createVoiceStateMachine(): VoiceStateMachine {
  return new VoiceStateMachine();
}
