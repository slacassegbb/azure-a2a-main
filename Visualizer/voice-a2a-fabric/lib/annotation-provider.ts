/**
 * ============================================================================
 * Annotation Provider System for Voice Live
 * ============================================================================
 * 
 * Provides pluggable annotation strategies for filling conversational gaps
 * during A2A network processing. Supports phased rollout:
 * 
 * - Phase 1: Simple post-function-call fillers
 * - Phase 2: Full event-based annotation queue with smart prioritization
 * 
 * Design Goals:
 * - Bulletproof state management
 * - Zero interruptions of user speech
 * - Graceful degradation
 * - Easy switching between strategies
 */

// ============================================================================
// Configuration & Types
// ============================================================================

export interface AnnotationConfig {
  /** Enable/disable annotations globally */
  enabled: boolean
  
  /** Minimum time (ms) between annotations to prevent spam */
  minGapMs: number
  
  /** Maximum number of queued annotations */
  maxQueueSize: number
  
  /** Timeout (ms) for stale annotations - drop if too old */
  maxAgeMs: number
}

export interface AnnotationEvent {
  /** Event type identifier */
  type: string
  
  /** Human-readable annotation message */
  message: string
  
  /** Priority for queue ordering */
  priority: 'low' | 'medium' | 'high'
  
  /** Timestamp when event was created */
  timestamp: number
  
  /** Optional metadata for debugging */
  metadata?: Record<string, any>
}

/**
 * Annotation statistics for monitoring and debugging
 */
export interface AnnotationStats {
  totalGenerated: number
  totalDelivered: number
  totalDropped: number
  queueSize: number
  lastAnnotationTime: number | null
}

// ============================================================================
// Base Interface
// ============================================================================

/**
 * Base annotation provider interface
 * Implement this to create custom annotation strategies
 */
export interface AnnotationProvider {
  /** Provider identifier for logging */
  readonly name: string
  
  /**
   * Check if provider has annotations ready to deliver
   * Must respect timing constraints (minGapMs, etc.)
   */
  shouldAnnotate(): boolean
  
  /**
   * Get next annotation message to inject
   * Returns null if no annotation ready or timing constraints not met
   */
  getNextAnnotation(): string | null
  
  /**
   * Notify provider that a function call was sent
   * @param functionName Name of the function being called
   * @param args Function arguments
   */
  onFunctionCallSent(functionName: string, args: any): void
  
  /**
   * Notify provider of A2A network event
   * @param eventType Type of event (tool_call, tool_response, etc.)
   * @param eventData Event payload
   */
  onEventReceived(eventType: string, eventData: any): void
  
  /**
   * Clear all pending annotations
   * Call when conversation resets or context changes
   */
  clear(): void
  
  /**
   * Get current statistics
   */
  getStats(): AnnotationStats
  
  /**
   * Update configuration dynamically
   */
  updateConfig(config: Partial<AnnotationConfig>): void
}

// ============================================================================
// PHASE 1: Simple Post-Function-Call Annotation Provider
// ============================================================================

/**
 * Simple provider that adds a single filler message after function calls
 * 
 * Features:
 * - Single annotation at a time (no queue complexity)
 * - Contextual messages based on function name
 * - Conservative timing to avoid spam
 * - Perfect for Phase 1 rollout
 */
export class PostFunctionCallAnnotationProvider implements AnnotationProvider {
  readonly name = 'PostFunctionCall'
  
  private pendingAnnotation: string | null = null
  private pendingTimestamp: number | null = null
  private lastAnnotationTime: number = 0
  private config: AnnotationConfig
  
  // Statistics
  private stats: AnnotationStats = {
    totalGenerated: 0,
    totalDelivered: 0,
    totalDropped: 0,
    queueSize: 0,
    lastAnnotationTime: null
  }
  
  constructor(config: Partial<AnnotationConfig> = {}) {
    this.config = {
      enabled: true,
      minGapMs: 2000, // 2 seconds minimum between annotations
      maxQueueSize: 1, // Only one pending at a time
      maxAgeMs: 10000, // Drop annotations older than 10 seconds
      ...config
    }
    
    console.log(`[${this.name}] Initialized with config:`, this.config)
  }
  
  shouldAnnotate(): boolean {
    if (!this.config.enabled) {
      return false
    }
    
    if (!this.pendingAnnotation || !this.pendingTimestamp) {
      return false
    }
    
    // Check if annotation is too stale
    const age = Date.now() - this.pendingTimestamp
    if (age > this.config.maxAgeMs) {
      console.log(`[${this.name}] ⚠️ Dropping stale annotation (age: ${age}ms)`)
      this.pendingAnnotation = null
      this.pendingTimestamp = null
      this.stats.totalDropped++
      return false
    }
    
    // Check minimum gap since last annotation
    const timeSinceLastAnnotation = Date.now() - this.lastAnnotationTime
    if (timeSinceLastAnnotation < this.config.minGapMs) {
      return false
    }
    
    return true
  }
  
  getNextAnnotation(): string | null {
    if (!this.shouldAnnotate()) {
      return null
    }
    
    const annotation = this.pendingAnnotation
    this.pendingAnnotation = null
    this.pendingTimestamp = null
    this.lastAnnotationTime = Date.now()
    
    this.stats.totalDelivered++
    this.stats.queueSize = 0
    this.stats.lastAnnotationTime = this.lastAnnotationTime
    
    console.log(`[${this.name}] 🎤 Delivering annotation:`, annotation)
    return annotation
  }
  
  onFunctionCallSent(functionName: string, args: any): void {
    if (!this.config.enabled) {
      return
    }
    
    // Generate contextual filler based on function name
    const message = this.generateFillerMessage(functionName, args)
    
    // Only store if we don't already have a pending annotation
    if (!this.pendingAnnotation) {
      this.pendingAnnotation = message
      this.pendingTimestamp = Date.now()
      this.stats.totalGenerated++
      this.stats.queueSize = 1
      
      console.log(`[${this.name}] 📝 Queued filler message:`, message)
    } else {
      console.log(`[${this.name}] ⚠️ Already have pending annotation, skipping`)
      this.stats.totalDropped++
    }
  }
  
  onEventReceived(eventType: string, eventData: any): void {
    // Phase 1: Ignore events, only respond to function calls
    console.log(`[${this.name}] ℹ️ Ignoring event (Phase 1 mode):`, eventType)
  }
  
  clear(): void {
    const hadPending = !!this.pendingAnnotation
    this.pendingAnnotation = null
    this.pendingTimestamp = null
    this.stats.queueSize = 0
    
    if (hadPending) {
      console.log(`[${this.name}] 🧹 Cleared pending annotation`)
    }
  }
  
  getStats(): AnnotationStats {
    return { ...this.stats }
  }
  
  updateConfig(config: Partial<AnnotationConfig>): void {
    this.config = { ...this.config, ...config }
    console.log(`[${this.name}] Updated config:`, this.config)
  }
  
  // ============================================================================
  // Private Helpers
  // ============================================================================
  
  private generateFillerMessage(functionName: string, args: any): string {
    // Contextual fillers based on function name
    const fillerMessages: Record<string, string> = {
      'send_to_agent_network': 'Let me check on that for you...',
      'check_outage': 'I\'m checking our systems for any outages in your area...',
      'check_modem': 'Give me a moment to look at your modem status...',
      'check_network_performance': 'Let me analyze your network performance...',
      'schedule_technician': 'I\'m looking into technician availability...',
      'verify_account': 'Let me verify that information...',
    }
    
    // Try exact match
    if (fillerMessages[functionName]) {
      return fillerMessages[functionName]
    }
    
    // Try partial match
    for (const [key, message] of Object.entries(fillerMessages)) {
      if (functionName.includes(key) || key.includes(functionName)) {
        return message
      }
    }
    
    // Default fallback
    return 'One moment please, I\'m looking into that...'
  }
}

// ============================================================================
// PHASE 2: Event-Based Annotation Queue Provider
// ============================================================================

/**
 * Full-featured provider that annotates A2A network events
 * 
 * Features:
 * - Priority queue for smart ordering
 * - Automatic stale event cleanup
 * - Configurable event type filtering
 * - Rich contextual annotations
 * - Rate limiting to prevent spam
 */
export class EventBasedAnnotationProvider implements AnnotationProvider {
  readonly name = 'EventBased'
  
  private queue: AnnotationEvent[] = []
  private lastAnnotationTime: number = 0
  private config: AnnotationConfig
  
  // Event type configuration
  private enabledEventTypes: Set<string> = new Set([
    'function_call',
    'tool_call',
    'tool_response',
    'agent_activity',
    'inference_step'
  ])
  
  // Statistics
  private stats: AnnotationStats = {
    totalGenerated: 0,
    totalDelivered: 0,
    totalDropped: 0,
    queueSize: 0,
    lastAnnotationTime: null
  }
  
  constructor(config: Partial<AnnotationConfig> = {}) {
    this.config = {
      enabled: true,
      minGapMs: 3000, // 3 seconds minimum (more conservative for events)
      maxQueueSize: 10, // Keep up to 10 events
      maxAgeMs: 15000, // Drop events older than 15 seconds
      ...config
    }
    
    console.log(`[${this.name}] Initialized with config:`, this.config)
  }
  
  shouldAnnotate(): boolean {
    if (!this.config.enabled) {
      return false
    }
    
    // Cleanup stale events first
    this.cleanupStaleEvents()
    
    if (this.queue.length === 0) {
      return false
    }
    
    // Check minimum gap since last annotation
    const timeSinceLastAnnotation = Date.now() - this.lastAnnotationTime
    if (timeSinceLastAnnotation < this.config.minGapMs) {
      return false
    }
    
    return true
  }
  
  getNextAnnotation(): string | null {
    if (!this.shouldAnnotate()) {
      return null
    }
    
    // Sort by priority (high > medium > low) then timestamp (oldest first)
    this.queue.sort((a, b) => {
      const priorityOrder = { high: 0, medium: 1, low: 2 }
      const priorityDiff = priorityOrder[a.priority] - priorityOrder[b.priority]
      
      if (priorityDiff !== 0) {
        return priorityDiff // Higher priority first
      }
      
      return a.timestamp - b.timestamp // Older first
    })
    
    const event = this.queue.shift()
    if (!event) {
      return null
    }
    
    this.lastAnnotationTime = Date.now()
    this.stats.totalDelivered++
    this.stats.queueSize = this.queue.length
    this.stats.lastAnnotationTime = this.lastAnnotationTime
    
    console.log(`[${this.name}] 🎤 Delivering annotation:`, {
      type: event.type,
      priority: event.priority,
      message: event.message,
      age: Date.now() - event.timestamp,
      remainingQueue: this.queue.length
    })
    
    return event.message
  }
  
  onFunctionCallSent(functionName: string, args: any): void {
    if (!this.config.enabled) {
      return
    }
    
    const annotation = this.createFunctionCallAnnotation(functionName, args)
    this.addToQueue(annotation)
  }
  
  onEventReceived(eventType: string, eventData: any): void {
    if (!this.config.enabled) {
      return
    }
    
    // Check if event type is enabled
    if (!this.enabledEventTypes.has(eventType)) {
      console.log(`[${this.name}] ℹ️ Event type disabled:`, eventType)
      return
    }
    
    const annotation = this.createEventAnnotation(eventType, eventData)
    if (!annotation) {
      console.log(`[${this.name}] ℹ️ No annotation generated for event:`, eventType)
      return
    }
    
    this.addToQueue(annotation)
  }
  
  clear(): void {
    const previousSize = this.queue.length
    this.queue = []
    this.stats.queueSize = 0
    
    if (previousSize > 0) {
      console.log(`[${this.name}] 🧹 Cleared ${previousSize} pending annotations`)
    }
  }
  
  getStats(): AnnotationStats {
    return { ...this.stats }
  }
  
  updateConfig(config: Partial<AnnotationConfig>): void {
    this.config = { ...this.config, ...config }
    console.log(`[${this.name}] Updated config:`, this.config)
  }
  
  /**
   * Enable/disable specific event types
   */
  setEnabledEventTypes(types: string[]): void {
    this.enabledEventTypes = new Set(types)
    console.log(`[${this.name}] Updated enabled event types:`, Array.from(this.enabledEventTypes))
  }
  
  // ============================================================================
  // Private Helpers
  // ============================================================================
  
  private addToQueue(event: AnnotationEvent): void {
    // Prevent queue overflow
    if (this.queue.length >= this.config.maxQueueSize) {
      console.log(`[${this.name}] ⚠️ Queue full (${this.queue.length}/${this.config.maxQueueSize})`)
      
      // Try to remove oldest low-priority event
      const lowPriorityIndex = this.queue.findIndex(e => e.priority === 'low')
      if (lowPriorityIndex >= 0) {
        const dropped = this.queue.splice(lowPriorityIndex, 1)[0]
        console.log(`[${this.name}] ⚠️ Dropped low-priority event:`, dropped.type)
        this.stats.totalDropped++
      } else {
        // No low priority events, drop oldest
        const dropped = this.queue.shift()
        if (dropped) {
          console.log(`[${this.name}] ⚠️ Dropped oldest event:`, dropped.type)
          this.stats.totalDropped++
        }
      }
    }
    
    this.queue.push(event)
    this.stats.totalGenerated++
    this.stats.queueSize = this.queue.length
    
    console.log(`[${this.name}] 📝 Added to queue:`, {
      type: event.type,
      priority: event.priority,
      message: event.message,
      queueSize: this.queue.length
    })
  }
  
  private cleanupStaleEvents(): void {
    const now = Date.now()
    const initialSize = this.queue.length
    
    this.queue = this.queue.filter(event => {
      const age = now - event.timestamp
      if (age > this.config.maxAgeMs) {
        console.log(`[${this.name}] ⚠️ Dropping stale event:`, {
          type: event.type,
          age,
          maxAge: this.config.maxAgeMs
        })
        this.stats.totalDropped++
        return false
      }
      return true
    })
    
    const droppedCount = initialSize - this.queue.length
    if (droppedCount > 0) {
      this.stats.queueSize = this.queue.length
      console.log(`[${this.name}] 🧹 Cleaned up ${droppedCount} stale events`)
    }
  }
  
  private createFunctionCallAnnotation(functionName: string, args: any): AnnotationEvent {
    const annotations: Record<string, { message: string; priority: 'low' | 'medium' | 'high' }> = {
      'send_to_agent_network': {
        message: 'I\'m checking that with our specialist team...',
        priority: 'medium'
      },
      'check_outage': {
        message: 'Looking up outage information for your area...',
        priority: 'high'
      },
      'check_modem': {
        message: 'Analyzing your modem status...',
        priority: 'high'
      },
      'check_network_performance': {
        message: 'Running network diagnostics...',
        priority: 'medium'
      },
      'schedule_technician': {
        message: 'Checking technician availability...',
        priority: 'high'
      },
    }
    
    const annotation = annotations[functionName] || {
      message: 'Processing your request...',
      priority: 'low' as const
    }
    
    return {
      type: 'function_call',
      message: annotation.message,
      priority: annotation.priority,
      timestamp: Date.now(),
      metadata: { functionName, args }
    }
  }
  
  private createEventAnnotation(eventType: string, eventData: any): AnnotationEvent | null {
    switch (eventType) {
      case 'tool_call': {
        const toolName = eventData.tool_name || eventData.name || 'information'
        return {
          type: 'tool_call',
          message: `Checking ${toolName}...`,
          priority: 'low',
          timestamp: Date.now(),
          metadata: eventData
        }
      }
      
      case 'tool_response': {
        // Only annotate if it took a significant amount of time
        const duration = eventData.duration || 0
        if (duration < 2000) {
          return null // Too fast, skip annotation
        }
        
        return {
          type: 'tool_response',
          message: 'Got the information back...',
          priority: 'low',
          timestamp: Date.now(),
          metadata: eventData
        }
      }
      
      case 'inference_step': {
        return {
          type: 'inference',
          message: 'Our AI is analyzing the situation...',
          priority: 'low',
          timestamp: Date.now(),
          metadata: eventData
        }
      }
      
      case 'agent_activity':
      case 'remote_agent_activity': {
        const agentName = eventData.agent_name || eventData.name || 'specialist'
        const action = eventData.action || 'working on this'
        
        return {
          type: 'agent_activity',
          message: `The ${agentName} is ${action}...`,
          priority: 'medium',
          timestamp: Date.now(),
          metadata: eventData
        }
      }
      
      case 'agent_response': {
        // Only annotate if response took a while
        const duration = eventData.duration || 0
        if (duration < 3000) {
          return null
        }
        
        return {
          type: 'agent_response',
          message: 'Almost done checking...',
          priority: 'low',
          timestamp: Date.now(),
          metadata: eventData
        }
      }
      
      default:
        return null
    }
  }
}

// ============================================================================
// Factory & Utilities
// ============================================================================

export type AnnotationProviderType = 'simple' | 'events' | 'none'

/**
 * Factory function to create annotation providers
 * Provides easy switching between strategies
 * 
 * @param type Provider type: 'simple' (Phase 1), 'events' (Phase 2), or 'none' (disabled)
 * @param config Optional configuration overrides
 */
export function createAnnotationProvider(
  type: AnnotationProviderType,
  config?: Partial<AnnotationConfig>
): AnnotationProvider {
  console.log(`[AnnotationProvider] Creating provider: ${type}`)
  
  switch (type) {
    case 'simple':
      return new PostFunctionCallAnnotationProvider(config)
    
    case 'events':
      return new EventBasedAnnotationProvider(config)
    
    case 'none':
      return new PostFunctionCallAnnotationProvider({ ...config, enabled: false })
    
    default:
      console.warn(`[AnnotationProvider] Unknown type: ${type}, defaulting to 'simple'`)
      return new PostFunctionCallAnnotationProvider(config)
  }
}

/**
 * Null provider for testing or disabling annotations
 */
export class NullAnnotationProvider implements AnnotationProvider {
  readonly name = 'Null'
  
  shouldAnnotate(): boolean { return false }
  getNextAnnotation(): string | null { return null }
  onFunctionCallSent(): void { /* no-op */ }
  onEventReceived(): void { /* no-op */ }
  clear(): void { /* no-op */ }
  
  getStats(): AnnotationStats {
    return {
      totalGenerated: 0,
      totalDelivered: 0,
      totalDropped: 0,
      queueSize: 0,
      lastAnnotationTime: null
    }
  }
  
  updateConfig(): void { /* no-op */ }
}
