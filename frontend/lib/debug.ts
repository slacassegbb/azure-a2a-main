// Simple debug logging helpers gated by env flag.
export const DEBUG = process.env.NEXT_PUBLIC_DEBUG_LOGS === 'true'

export const logDebug = (...args: any[]) => {
  if (DEBUG) console.log(...args)
}

export const warnDebug = (...args: any[]) => {
  if (DEBUG) console.warn(...args)
}

