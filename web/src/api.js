const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000/api/web'

const MESSAGES = {
  400: 'Invalid request payload.',
  401: 'Authentication failed. Sign in again.',
  403: 'You do not have access to this action.',
  404: 'Requested data was not found.',
  409: 'Conflict: data was changed by another action.',
  422: 'Validation failed. Check form values.',
  429: 'Rate limit reached. Try again in a moment.',
  500: 'Server error. Try again later.',
  502: 'Upstream provider error. Retry shortly.',
  503: 'Service is temporarily unavailable.',
}

function ensureArray(value, label) {
  if (!Array.isArray(value)) throw new Error(`Invalid ${label} response shape`)
  return value
}

function ensureObject(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`Invalid ${label} response shape`)
  return value
}

function mapApiError(status, data) {
  const detail = typeof data?.detail === 'string' ? data.detail : typeof data?.error === 'string' ? data.error : null
  return detail || MESSAGES[status] || 'Request failed'
}

async function req(path, token, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(mapApiError(res.status, data))
  return data
}

export const api = {
  login: async (password) => ensureObject(await req('/auth/login', null, { method: 'POST', body: JSON.stringify({ password }) }), 'login'),
  me: async (token) => ensureObject(await req('/me', token), 'me'),
  subjects: async (token) => ensureArray(await req('/subjects', token), 'subjects'),
  topics: async (token) => ensureArray(await req('/topics', token), 'topics'),
  messages: async (token, topicId) => ensureArray(await req(`/messages${topicId ? `?topic_id=${topicId}` : ''}`, token), 'messages'),
  search: async (token, query, topicId, facets = {}) => {
    const params = new URLSearchParams({ q: query })
    if (topicId) params.set('topic_id', topicId)
    if (facets.kind) params.set('kind', facets.kind)
    if (facets.tag) params.set('tag', facets.tag)
    if (facets.dateFrom) params.set('date_from', facets.dateFrom)
    if (facets.dateTo) params.set('date_to', facets.dateTo)
    return ensureArray(await req(`/memory/search?${params.toString()}`, token), 'search')
  },
  notes: async (token, topicId) => ensureArray(await req(`/notes${topicId ? `?topic_id=${topicId}` : ''}`, token), 'notes'),
  updateNote: async (token, noteId, payload) => ensureObject(await req(`/notes/${noteId}`, token, { method: 'PATCH', body: JSON.stringify(payload) }), 'updateNote'),
  flashcards: async (token, topicId, dueOnly = false) => ensureArray(await req(`/flashcards${topicId ? `?topic_id=${topicId}${dueOnly ? '&due_only=true' : ''}` : dueOnly ? '?due_only=true' : ''}`, token), 'flashcards'),
  reviewFlashcard: (token, cardId, action) => req(`/flashcards/${cardId}/review`, token, { method: 'POST', body: JSON.stringify({ action }) }),
  stats: async (token) => ensureObject(await req('/stats', token), 'stats'),
  exportData: async (token) => ensureObject(await req('/privacy/export', token), 'exportData'),
  modelSettings: async (token) => ensureObject(await req('/admin/model-settings', token), 'modelSettings'),
  adminErrors: async (token) => ensureArray(await req('/admin/errors', token), 'adminErrors'),
  adminFeedback: async (token) => ensureArray(await req('/admin/feedback', token), 'adminFeedback'),
  adminCostBudgetAlert: async (token) => ensureObject(await req('/admin/alerts/cost-budget', token), 'adminCostBudgetAlert'),
  adminAnalyticsSummary: async (token, days = 30) => ensureObject(await req(`/admin/analytics/summary?days=${days}`, token), 'adminAnalyticsSummary'),
  adminJourneyHealth: async (token, days = 30) => ensureObject(await req(`/admin/analytics/journey-health?days=${days}`, token), 'adminJourneyHealth'),
  updateFeedback: async (token, feedbackId, payload) => ensureObject(await req(`/admin/feedback/${feedbackId}`, token, { method: 'PATCH', body: JSON.stringify(payload) }), 'updateFeedback'),
  sourceCoverage: async (token) => ensureObject(await req('/admin/evidence/source-coverage', token), 'sourceCoverage'),
  needsCheck: async (token) => ensureArray(await req('/admin/evidence/needs-check', token), 'needsCheck'),
  trustSafetyTrace: async (token) => ensureArray(await req('/admin/trust-safety-trace', token), 'trustSafetyTrace'),
}
