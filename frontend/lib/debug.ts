// Simple debug logging helpers gated by env flag.
export const DEBUG = process.env.NEXT_PUBLIC_DEBUG_LOGS === 'true'

export const logDebug = (...args: any[]) => {
  if (DEBUG) console.log(...args)
}

export const warnDebug = (...args: any[]) => {
  if (DEBUG) console.warn(...args)
}

// Errors should generally still surface regardless of flag.
export const errorLog = (...args: any[]) => console.error(...args)

