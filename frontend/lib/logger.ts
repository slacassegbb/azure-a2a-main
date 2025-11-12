/**
 * Centralized structured logging for the A2A Frontend.
 * 
 * Provides context-aware logging with categories and better formatting.
 * Set NEXT_PUBLIC_VERBOSE_LOGGING=true in environment to see detailed debug logs.
 */

import { config } from './config';

/**
 * Log level enumeration
 */
export enum LogLevel {
  DEBUG = 'DEBUG',
  INFO = 'INFO',
  SUCCESS = 'SUCCESS',
  WARNING = 'WARNING',
  ERROR = 'ERROR',
}

/**
 * Log category for better filtering and context
 */
export enum LogCategory {
  SYSTEM = 'SYSTEM',
  WEBSOCKET = 'WEBSOCKET',
  VOICE = 'VOICE',
  A2A = 'A2A',
  AUTH = 'AUTH',
  UI = 'UI',
  AUDIO = 'AUDIO',
  NETWORK = 'NETWORK',
}

/**
 * Context type for structured logging
 */
export type LogContext = Record<string, any>;

/**
 * Format a structured log message
 */
function formatLog(
  level: LogLevel,
  message: string,
  category?: LogCategory,
  context?: LogContext
): string {
  const timestamp = new Date().toISOString().split('T')[1].substring(0, 12);
  
  // Build prefix
  let prefix: string;
  switch (level) {
    case LogLevel.SUCCESS:
      prefix = '✅';
      break;
    case LogLevel.WARNING:
      prefix = '⚠️';
      break;
    case LogLevel.ERROR:
      prefix = '❌';
      break;
    default:
      prefix = `[${level}]`;
  }
  
  // Add category if provided
  if (category) {
    prefix = `${prefix} [${category}]`;
  }
  
  return `${timestamp} ${prefix} ${message}`;
}

/**
 * Log with context
 */
function logWithContext(
  level: LogLevel,
  consoleMethod: (...args: any[]) => void,
  message: string,
  category?: LogCategory,
  context?: LogContext
): void {
  const formattedMessage = formatLog(level, message, category, context);
  
  if (context && (config.verboseLogging || level === LogLevel.ERROR)) {
    consoleMethod(formattedMessage, '\n  Context:', context);
  } else {
    consoleMethod(formattedMessage);
  }
}

/**
 * Log informational messages (always shown)
 */
export function logInfo(
  message: string,
  category?: LogCategory,
  context?: LogContext
): void {
  logWithContext(LogLevel.INFO, console.log, message, category, context);
}

/**
 * Log success messages (always shown)
 */
export function logSuccess(
  message: string,
  category?: LogCategory,
  context?: LogContext
): void {
  logWithContext(LogLevel.SUCCESS, console.log, message, category, context);
}

/**
 * Log warning messages (always shown)
 */
export function logWarning(
  message: string,
  category?: LogCategory,
  context?: LogContext
): void {
  logWithContext(LogLevel.WARNING, console.warn, message, category, context);
}

/**
 * Log error messages (always shown)
 */
export function logError(
  message: string,
  category?: LogCategory,
  context?: LogContext,
  error?: Error
): void {
  const errorContext = error ? { ...context, error: error.message, stack: error.stack } : context;
  logWithContext(LogLevel.ERROR, console.error, message, category, errorContext);
}

/**
 * Log debug messages (only shown when VERBOSE_LOGGING=true)
 */
export function logDebug(
  message: string,
  category?: LogCategory,
  context?: LogContext
): void {
  if (config.verboseLogging) {
    logWithContext(LogLevel.DEBUG, console.log, message, category, context);
  }
}

/**
 * Category-specific logging helpers
 */

export function logWebSocketDebug(message: string, context?: LogContext): void {
  logDebug(message, LogCategory.WEBSOCKET, context);
}

export function logVoiceDebug(message: string, context?: LogContext): void {
  logDebug(message, LogCategory.VOICE, context);
}

export function logA2ADebug(message: string, context?: LogContext): void {
  logDebug(message, LogCategory.A2A, context);
}

export function logAudioDebug(message: string, context?: LogContext): void {
  logDebug(message, LogCategory.AUDIO, context);
}

export function logNetworkDebug(message: string, context?: LogContext): void {
  logDebug(message, LogCategory.NETWORK, context);
}

export function logAuthDebug(message: string, context?: LogContext): void {
  logDebug(message, LogCategory.AUTH, context);
}

export function logUIDebug(message: string, context?: LogContext): void {
  logDebug(message, LogCategory.UI, context);
}

/**
 * Performance measurement helpers
 */

const performanceTimers = new Map<string, number>();

export function startTimer(label: string): void {
  performanceTimers.set(label, performance.now());
  logDebug(`Started timer: ${label}`, LogCategory.SYSTEM);
}

export function endTimer(label: string, category?: LogCategory): void {
  const startTime = performanceTimers.get(label);
  if (startTime) {
    const elapsed = performance.now() - startTime;
    logDebug(`Timer ${label}: ${elapsed.toFixed(2)}ms`, category);
    performanceTimers.delete(label);
  }
}

/**
 * Group logging for better organization
 */

export function logGroup(title: string, category?: LogCategory): void {
  if (config.verboseLogging) {
    console.group(formatLog(LogLevel.DEBUG, title, category));
  }
}

export function logGroupEnd(): void {
  if (config.verboseLogging) {
    console.groupEnd();
  }
}

/**
 * Export logger object for convenience
 */
export const logger = {
  info: logInfo,
  success: logSuccess,
  warning: logWarning,
  error: logError,
  debug: logDebug,
  
  // Category-specific
  websocket: logWebSocketDebug,
  voice: logVoiceDebug,
  a2a: logA2ADebug,
  audio: logAudioDebug,
  network: logNetworkDebug,
  auth: logAuthDebug,
  ui: logUIDebug,
  
  // Performance
  startTimer,
  endTimer,
  
  // Grouping
  group: logGroup,
  groupEnd: logGroupEnd,
};

export default logger;
