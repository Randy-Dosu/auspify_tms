/**
 * Thin API client.
 *
 * All backend calls go through `request()` so that base URL handling,
 * timeouts, JSON parsing and error normalisation live in exactly one place.
 *
 * The base URL is a relative path by default ("/api"), which the Vite dev
 * server proxies to Flask. Set VITE_API_BASE_URL to override it.
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

/** Error type that carries the HTTP status and the server's message. */
export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/**
 * Perform a JSON request against the API.
 * @param {string} path   e.g. "/health" (relative to API_BASE_URL)
 * @param {object} options fetch options; `body` objects are JSON-encoded
 */
export async function request(path, options = {}) {
  const { body, headers, ...rest } = options

  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      // Send/receive cookies only if we later adopt cookie sessions.
      credentials: 'same-origin',
      ...rest,
      headers: {
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...headers,
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
  } catch {
    // Network-level failure (server down, DNS, offline).
    throw new ApiError('Cannot reach the API. Is the backend running?', 0)
  }

  // Parse JSON defensively: the server may return HTML for proxied errors.
  let payload = null
  const text = await response.text()
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    // Backend errors look like { error: { code, message } }.
    const message =
      payload?.error?.message || `Request failed with status ${response.status}`
    throw new ApiError(message, response.status)
  }

  return payload
}

/** GET /api/health - liveness probe used by the setup page. */
export function getHealth() {
  return request('/health')
}
