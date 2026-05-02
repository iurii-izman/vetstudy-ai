const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000/api/web'

async function req(path, token, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    const detail = typeof data.detail === 'string' ? data.detail : data.error || 'Request failed'
    throw new Error(detail)
  }
  return res.json()
}

export const api = {
  login: (password) => req('/auth/login', null, { method: 'POST', body: JSON.stringify({ password }) }),
  me: (token) => req('/me', token),
  subjects: (token) => req('/subjects', token),
  topics: (token) => req('/topics', token),
  sessions: (token, topicId) => req(`/sessions${topicId ? `?topic_id=${topicId}` : ''}`, token),
  messages: (token, topicId) => req(`/messages${topicId ? `?topic_id=${topicId}` : ''}`, token),
  search: (token, query, topicId) => {
    const params = new URLSearchParams({ q: query })
    if (topicId) params.set('topic_id', topicId)
    return req(`/memory/search?${params.toString()}`, token)
  },
  notes: (token, topicId) => req(`/notes${topicId ? `?topic_id=${topicId}` : ''}`, token),
  updateNote: (token, noteId, payload) => req(`/notes/${noteId}`, token, { method: 'PATCH', body: JSON.stringify(payload) }),
  flashcards: (token, topicId) => req(`/flashcards${topicId ? `?topic_id=${topicId}` : ''}`, token),
  stats: (token) => req('/stats', token),
  exportData: (token) => req('/privacy/export', token),
  modelSettings: (token) => req('/admin/model-settings', token),
}
