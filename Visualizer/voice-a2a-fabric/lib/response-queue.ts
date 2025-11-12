/**
 * Response Queue for managing A2A responses to Voice Live API.
 * 
 * This provides a clean, reliable way to match network responses with
 * pending function calls, replacing fragile string-based matching.
 */

export interface PendingResponse {
  messageId: string;
  callId: string;
  timestamp: number;
  agentName?: string;
  timeout?: NodeJS.Timeout;
}

export interface CompletedResponse {
  messageId: string;
  callId: string;
  content: string;
  completedAt: number;
}

/**
 * Response queue for managing pending and completed responses
 */
export class ResponseQueue {
  private pending: Map<string, PendingResponse> = new Map();
  private completed: Map<string, CompletedResponse> = new Map();
  private maxCompletedSize = 50; // Keep last 50 for debugging
  private defaultTimeout = 30000; // 30 seconds

  /**
   * Add a pending response to the queue
   */
  addPending(messageId: string, callId: string, agentName?: string, timeoutMs?: number): void {
    const pending: PendingResponse = {
      messageId,
      callId,
      timestamp: Date.now(),
      agentName,
    };

    // Set timeout for cleanup
    const timeout = setTimeout(() => {
      console.warn(`[ResponseQueue] Timeout for ${messageId} (call_id: ${callId})`);
      this.removePending(messageId);
    }, timeoutMs || this.defaultTimeout);

    pending.timeout = timeout;
    this.pending.set(messageId, pending);

    console.log(`[ResponseQueue] Added pending: ${messageId} → ${callId}`, {
      totalPending: this.pending.size,
      agent: agentName,
    });
  }

  /**
   * Get pending response by messageId
   */
  getPendingByMessageId(messageId: string): PendingResponse | undefined {
    return this.pending.get(messageId);
  }

  /**
   * Get pending response by callId
   */
  getPendingByCallId(callId: string): PendingResponse | undefined {
    for (const [_, pending] of this.pending) {
      if (pending.callId === callId) {
        return pending;
      }
    }
    return undefined;
  }

  /**
   * Find the oldest pending response (FIFO for voice sessions)
   */
  getOldestPending(): PendingResponse | undefined {
    let oldest: PendingResponse | undefined;
    
    for (const [_, pending] of this.pending) {
      if (!oldest || pending.timestamp < oldest.timestamp) {
        oldest = pending;
      }
    }
    
    return oldest;
  }

  /**
   * Complete a response
   */
  completePending(messageId: string, content: string): CompletedResponse | null {
    const pending = this.pending.get(messageId);
    
    if (!pending) {
      console.warn(`[ResponseQueue] No pending response for ${messageId}`);
      return null;
    }

    // Clear timeout
    if (pending.timeout) {
      clearTimeout(pending.timeout);
    }

    // Create completed response
    const completed: CompletedResponse = {
      messageId: pending.messageId,
      callId: pending.callId,
      content,
      completedAt: Date.now(),
    };

    // Move from pending to completed
    this.pending.delete(messageId);
    this.completed.set(messageId, completed);

    // Trim completed queue if too large
    if (this.completed.size > this.maxCompletedSize) {
      const oldestKey = this.completed.keys().next().value;
      if (oldestKey) {
        this.completed.delete(oldestKey);
      }
    }

    console.log(`[ResponseQueue] Completed: ${messageId}`, {
      callId: completed.callId,
      elapsed: completed.completedAt - pending.timestamp,
      remainingPending: this.pending.size,
    });

    return completed;
  }

  /**
   * Remove a pending response
   */
  removePending(messageId: string): boolean {
    const pending = this.pending.get(messageId);
    
    if (pending) {
      if (pending.timeout) {
        clearTimeout(pending.timeout);
      }
      this.pending.delete(messageId);
      console.log(`[ResponseQueue] Removed pending: ${messageId}`);
      return true;
    }
    
    return false;
  }

  /**
   * Get all pending responses
   */
  getAllPending(): PendingResponse[] {
    return Array.from(this.pending.values());
  }

  /**
   * Get all completed responses
   */
  getAllCompleted(): CompletedResponse[] {
    return Array.from(this.completed.values());
  }

  /**
   * Get pending count
   */
  getPendingCount(): number {
    return this.pending.size;
  }

  /**
   * Clear all pending responses
   */
  clearPending(): void {
    // Clear all timeouts
    for (const [_, pending] of this.pending) {
      if (pending.timeout) {
        clearTimeout(pending.timeout);
      }
    }
    
    this.pending.clear();
    console.log('[ResponseQueue] Cleared all pending responses');
  }

  /**
   * Clear all responses (pending and completed)
   */
  clearAll(): void {
    this.clearPending();
    this.completed.clear();
    console.log('[ResponseQueue] Cleared all responses');
  }

  /**
   * Get debug info
   */
  getDebugInfo(): {
    pendingCount: number;
    completedCount: number;
    pendingDetails: Array<{ messageId: string; callId: string; age: number; agent?: string }>;
  } {
    const now = Date.now();
    
    return {
      pendingCount: this.pending.size,
      completedCount: this.completed.size,
      pendingDetails: Array.from(this.pending.values()).map(p => ({
        messageId: p.messageId,
        callId: p.callId,
        age: now - p.timestamp,
        agent: p.agentName,
      })),
    };
  }
}

/**
 * Create a new response queue instance
 */
export function createResponseQueue(): ResponseQueue {
  return new ResponseQueue();
}
