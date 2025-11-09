/**
 * Debug utility functions
 */

export const DEBUG = process.env.NEXT_PUBLIC_DEBUG_LOGS === 'true';

export function logDebug(...args: any[]) {
  if (DEBUG) {
    console.log(...args);
  }
}

export function warnDebug(...args: any[]) {
  if (DEBUG) {
    console.warn(...args);
  }
}
