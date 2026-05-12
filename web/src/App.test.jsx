import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

const token = 'tok'

function installFetchMock(overrides = {}) {
  global.fetch = vi.fn(async (url, options = {}) => {
    const u = String(url)
    const method = options.method || 'GET'

    if (u.includes('/memory/search')) return { ok: true, json: async () => [{ id: 's1', content: 'Found item', kind: 'note' }] }
    if (u.includes('/messages')) return { ok: true, json: async () => [] }
    if (u.includes('/me')) return { ok: true, json: async () => ({ role: 'owner', profile: {} }) }
    if (u.includes('/topics')) return { ok: true, json: async () => [{ id: '11111111-1111-1111-1111-111111111111', title: 'Surgery', subject_id: null }] }
    if (u.includes('/subjects')) return { ok: true, json: async () => [] }
    if (u.includes('/stats')) return { ok: true, json: async () => ({ topics_total: 1, due_flashcards: 1 }) }
    if (u.includes('/admin/model-settings')) return { ok: true, json: async () => ({}) }
    if (u.includes('/notes')) return { ok: true, json: async () => [{ id: 'n1', content: 'Old note', kind: 'note' }] }
    if (u.includes('/flashcards/') && method === 'POST') return { ok: true, json: async () => ({}) }
    if (u.includes('/flashcards')) return { ok: true, json: async () => [{ id: 'c1', front: 'Q', back: 'A', interval_days: 1 }] }
    if (u.includes('/admin/errors')) return { ok: true, json: async () => [{ id: 'e1', category: 'provider_timeout' }] }
    if (u.includes('/admin/feedback/f1') && method === 'PATCH') {
      if (overrides.feedbackPatchFail) return { ok: false, status: 500, json: async () => ({ detail: 'failed' }) }
      return { ok: true, json: async () => ({ id: 'f1', status: 'resolved' }) }
    }
    if (u.includes('/admin/feedback')) return { ok: true, json: async () => [{ id: 'f1', feedback_type: 'down', status: 'new' }] }
    if (u.includes('/admin/analytics/summary')) return { ok: true, json: async () => ({ behavior: { high_risk_query_count: 2 }, content_gap_report: { zero_results_total: 1, zero_results_by_topic: { Surgery: 1 } }, journey_health: { drop_points: { provider_error: 1 }, recovery_rate: 0.5, first_week_completion_rate: 0.4, first_value_10m_rate: 0.8 } }) }
    if (u.includes('/admin/evidence/source-coverage')) return { ok: true, json: async () => ({ missing: false, total_sources: 2 }) }
    if (u.includes('/admin/evidence/needs-check')) return { ok: true, json: async () => [] }
    if (u.includes('/admin/trust-safety-trace')) return { ok: true, json: async () => [] }
    if (u.includes('/privacy/export')) return { ok: true, json: async () => ({ ok: true }) }
    return { ok: true, json: async () => ({}) }
  })
}

describe('App', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('renders login first', () => {
    render(<MemoryRouter><App /></MemoryRouter>)
    expect(screen.getByText('VetStudy AI Cabinet')).toBeInTheDocument()
  })

  it('supports search flow', async () => {
    localStorage.setItem('vetstudy-token', token)
    installFetchMock()
    render(<MemoryRouter><App /></MemoryRouter>)

    const input = await screen.findByPlaceholderText('Search memory')
    await userEvent.type(input, 'Found')
    await userEvent.click(screen.getByText('Search'))

    await waitFor(() => expect(screen.getByText('Found item')).toBeInTheDocument())
  })

  it('supports review and admin optimistic feedback update', async () => {
    localStorage.setItem('vetstudy-token', token)
    installFetchMock()
    render(<MemoryRouter><App /></MemoryRouter>)

    await screen.findByText('VetStudy')
    await userEvent.click(screen.getByText('Review'))
    await screen.findByText('Ответ скрыт. Сначала раскройте карточку.')
    await userEvent.click(screen.getByText('Reveal'))
    await screen.findByText('A')

    await userEvent.click(screen.getByText('Admin'))
    await screen.findByText('Open negative feedback')
    await screen.findByText('Journey Health')
    await screen.findByText('provider_error (1)')
    await userEvent.click(screen.getByText('resolved'))
    await waitFor(() => expect(global.fetch).toHaveBeenCalled())
  })
})
