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

// Guard against multiple simultaneous 401 handlers firing
let isHandlingExpiry = false

/**
 * Handle session expiry: clear auth state and reload to show login screen.
 * Debounced so multiple 401 responses don't trigger multiple reloads.
 */
export function handleSessionExpired(): void {
  if (typeof window === 'undefined' || isHandlingExpiry) return
  if (!getAuthToken()) return // not logged in, nothing to expire

  isHandlingExpiry = true
  sessionStorage.removeItem('auth_token')
  sessionStorage.removeItem('user_info')
  localStorage.removeItem('auth_token')

  // Brief alert so the user knows why they're being redirected
  alert('Your session has expired. Please log in again.')
  window.location.reload()
}

/**
 * Wrapper around fetch that auto-injects auth headers and handles 401.
 * Drop-in replacement for `fetch()` in authenticated API calls.
 */
export async function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers)
  const token = getAuthToken()
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(input, { ...init, headers })

  if (response.status === 401 && getAuthToken()) {
    handleSessionExpired()
  }

  return response
}
