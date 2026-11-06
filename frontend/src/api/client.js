/**
 * Thin API client.
 *
 * Every backend call goes through `request()` so base URL handling, token
 * injection, JSON parsing and error normalisation live in exactly one place.
 *
 * The base URL is a relative path ("/api"), which Vite proxies to Flask in
 * development and which works unchanged behind a reverse proxy in production.
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')
const TOKEN_KEY = 'auspify.access_token'

/** Error type carrying the HTTP status and the server's message. */
export class ApiError extends Error {
  constructor(message, status, fields) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.fields = fields || null
  }
}

/**
 * Token storage.
 * localStorage keeps the session across reloads. The token is short-lived and
 * is sent only in the Authorization header - never in a URL or a cookie.
 */
export const tokenStore = {
  get: () => {
    try {
      return localStorage.getItem(TOKEN_KEY)
    } catch {
      return null
    }
  },
  set: (token) => {
    try {
      localStorage.setItem(TOKEN_KEY, token)
    } catch {
      /* storage disabled - session lasts until reload */
    }
  },
  clear: () => {
    try {
      localStorage.removeItem(TOKEN_KEY)
    } catch {
      /* ignore */
    }
  },
}

/**
 * Perform a JSON request against the API.
 * @param {string} path relative to API_BASE_URL, e.g. "/auth/login"
 * @param {object} options fetch options; `body` objects are JSON-encoded
 */
export async function request(path, options = {}) {
  const { body, headers, auth = true, ...rest } = options
  const token = auth ? tokenStore.get() : null

  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      headers: {
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
  } catch {
    throw new ApiError('Cannot reach the API. Is the backend running?', 0)
  }

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
    const message = payload?.error?.message || `Request failed with status ${response.status}`
    throw new ApiError(message, response.status, payload?.error?.fields)
  }

  return payload
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------
export function getHealth() {
  return request('/health', { auth: false })
}

export const authApi = {
  login: (email, password) =>
    request('/auth/login', { method: 'POST', auth: false, body: { email, password } }),
  register: (fullName, email, password) =>
    request('/auth/register', {
      method: 'POST',
      auth: false,
      body: { full_name: fullName, email, password },
    }),
  me: () => request('/auth/me'),
  logout: () => request('/auth/logout', { method: 'POST' }),
}

// ---------------------------------------------------------------------------
// Step 2: exams and attempts
// ---------------------------------------------------------------------------
export const examsApi = {
  list: () => request('/exams'),
  get: (id) => request(`/exams/${id}`),
  create: (body) => request('/exams', { method: 'POST', body }),
  update: (id, body) => request(`/exams/${id}`, { method: 'PUT', body }),
  remove: (id) => request(`/exams/${id}`, { method: 'DELETE' }),
  questions: (id) => request(`/exams/${id}/questions`),
  addQuestion: (id, body) => request(`/exams/${id}/questions`, { method: 'POST', body }),
  updateQuestion: (qid, body) => request(`/questions/${qid}`, { method: 'PUT', body }),
  deleteQuestion: (qid) => request(`/questions/${qid}`, { method: 'DELETE' }),
}

export const attemptsApi = {
  start: (examId) => request(`/exams/${examId}/start`, { method: 'POST' }),
  get: (id) => request(`/attempts/${id}`),
  answer: (id, body) => request(`/attempts/${id}/answer`, { method: 'PUT', body }),
  submit: (id) => request(`/attempts/${id}/submit`, { method: 'POST' }),
}
