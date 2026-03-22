/**
 * Auth utilities - uses localStorage for persistent login across sessions.
 */

export function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null
  const token = localStorage.getItem('auth_token')
  if (!token) return null

  // Check if JWT is expired
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    if (payload.exp && payload.exp * 1000 < Date.now()) {
      // Token expired — clear it
      localStorage.removeItem('auth_token')
      localStorage.removeItem('user_info')
      return null
    }
  } catch {}

  return token
}

export function getAuthHeaders(): HeadersInit {
  const token = getAuthToken()
  const headers: HeadersInit = { 'Content-Type': 'application/json' }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

let isHandlingExpiry = false

export function handleSessionExpired(): void {
  if (typeof window === 'undefined' || isHandlingExpiry) return
  if (!getAuthToken()) return

  isHandlingExpiry = true
  localStorage.removeItem('auth_token')
  localStorage.removeItem('user_info')

  alert('Your session has expired. Please log in again.')
  window.location.reload()
}

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

export function getUserInfo(): { user_id: string; email: string; name: string; color: string } | null {
  if (typeof window === 'undefined') return null
  const info = localStorage.getItem('user_info')
  if (!info) return null
  try {
    return JSON.parse(info)
  } catch {
    return null
  }
}

export function getUserIdFromToken(): string | null {
  const token = getAuthToken()
  if (!token) return null
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return payload.user_id || null
  } catch {
    return null
  }
}
