/**
 * Shared authentication utilities.
 *
 * Single source of truth for reading the auth token from storage
 * and building Authorization headers for backend API calls.
 */

/**
 * Get auth token from session or local storage.
 * Returns null when running server-side or when no token is stored.
 */
export function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null
  return sessionStorage.getItem('auth_token') || localStorage.getItem('auth_token')
}

/**
 * Build standard headers for authenticated API calls.
 * Includes Content-Type and, if available, an Authorization bearer token.
 */
export function getAuthHeaders(): HeadersInit {
  const token = getAuthToken()
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}
