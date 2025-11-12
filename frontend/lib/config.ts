/**
 * Centralized configuration management for the A2A Frontend.
 * 
 * All environment variables and defaults are defined here for easy maintenance.
 * This module provides type-safe access to configuration with validation.
 */

/**
 * Configuration interface for type safety
 */
export interface AppConfig {
  // API Configuration
  apiBaseUrl: string;
  websocketUrl: string;
  
  // Voice Live API
  voiceLiveEnabled: boolean;
  
  // Feature Flags
  debugMode: boolean;
  verboseLogging: boolean;
  
  // UI Configuration
  theme: 'light' | 'dark' | 'system';
  
  // Performance
  wsReconnectDelay: number;
  wsMaxReconnectAttempts: number;
  voiceReconnectDelay: number;
  voiceMaxReconnectAttempts: number;
}

/**
 * Get boolean value from environment variable
 */
function getBool(key: string, defaultValue: boolean = false): boolean {
  if (typeof window === 'undefined') {
    return defaultValue;
  }
  const value = process.env[key];
  if (!value) return defaultValue;
  return value.toLowerCase() === 'true' || value === '1';
}

/**
 * Get number value from environment variable
 */
function getNumber(key: string, defaultValue: number): number {
  if (typeof window === 'undefined') {
    return defaultValue;
  }
  const value = process.env[key];
  if (!value) return defaultValue;
  const parsed = parseInt(value, 10);
  return isNaN(parsed) ? defaultValue : parsed;
}

/**
 * Load configuration from environment variables with defaults
 */
function loadConfig(): AppConfig {
  // Determine if we're in browser
  const isBrowser = typeof window !== 'undefined';
  
  // Get base URLs from environment or defaults
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 
                     (isBrowser ? `http://${window.location.hostname}:12000` : 'http://localhost:12000');
  
  const websocketUrl = process.env.NEXT_PUBLIC_WEBSOCKET_URL || 
                       (isBrowser ? `ws://${window.location.hostname}:8080` : 'ws://localhost:8080');
  
  return {
    // API Configuration
    apiBaseUrl,
    websocketUrl,
    
    // Voice Live API
    voiceLiveEnabled: getBool('NEXT_PUBLIC_VOICE_LIVE_ENABLED', true),
    
    // Feature Flags
    debugMode: getBool('NEXT_PUBLIC_DEBUG_MODE', false),
    verboseLogging: getBool('NEXT_PUBLIC_VERBOSE_LOGGING', false),
    
    // UI Configuration
    theme: (process.env.NEXT_PUBLIC_THEME as 'light' | 'dark' | 'system') || 'system',
    
    // Performance - WebSocket
    wsReconnectDelay: getNumber('NEXT_PUBLIC_WS_RECONNECT_DELAY', 2000),
    wsMaxReconnectAttempts: getNumber('NEXT_PUBLIC_WS_MAX_RECONNECT_ATTEMPTS', 5),
    
    // Performance - Voice
    voiceReconnectDelay: getNumber('NEXT_PUBLIC_VOICE_RECONNECT_DELAY', 3000),
    voiceMaxReconnectAttempts: getNumber('NEXT_PUBLIC_VOICE_MAX_RECONNECT_ATTEMPTS', 3),
  };
}

/**
 * Validate configuration and return warnings
 */
function validateConfig(config: AppConfig): string[] {
  const warnings: string[] = [];
  
  if (!config.apiBaseUrl) {
    warnings.push('⚠️ API_BASE_URL not configured');
  }
  
  if (!config.websocketUrl) {
    warnings.push('⚠️ WEBSOCKET_URL not configured');
  }
  
  if (!config.voiceLiveEnabled) {
    warnings.push('⚠️ Voice Live features are disabled');
  }
  
  return warnings;
}

/**
 * Display configuration summary (for debugging)
 */
export function displayConfigSummary(config: AppConfig): void {
  if (!config.debugMode && !config.verboseLogging) {
    return; // Don't log in production
  }
  
  console.group('🔧 A2A Frontend Configuration');
  console.log('API Base URL:', config.apiBaseUrl);
  console.log('WebSocket URL:', config.websocketUrl);
  console.log('Voice Live:', config.voiceLiveEnabled ? '✓ Enabled' : '✗ Disabled');
  console.log('Debug Mode:', config.debugMode);
  console.log('Verbose Logging:', config.verboseLogging);
  console.log('Theme:', config.theme);
  console.log('WS Reconnect:', `${config.wsReconnectDelay}ms, max ${config.wsMaxReconnectAttempts} attempts`);
  console.log('Voice Reconnect:', `${config.voiceReconnectDelay}ms, max ${config.voiceMaxReconnectAttempts} attempts`);
  
  const warnings = validateConfig(config);
  if (warnings.length > 0) {
    console.group('⚠️ Configuration Warnings');
    warnings.forEach(w => console.warn(w));
    console.groupEnd();
  }
  
  console.groupEnd();
}

/**
 * Global configuration instance
 * This is loaded once at module import time
 */
export const config: AppConfig = loadConfig();

/**
 * Export validation function for testing
 */
export { validateConfig };

// Display config on load in development
if (typeof window !== 'undefined') {
  displayConfigSummary(config);
}
