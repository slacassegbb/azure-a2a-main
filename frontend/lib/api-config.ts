/**
 * Single source of truth for the backend API base URL.
 *
 * Every file that needs to call the backend should import from here
 * instead of re-reading the environment variable inline.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000'
