import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

const token = 'tok'

describe('App', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('renders login first', () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByText('VetStudy AI Cabinet')).toBeInTheDocument()
  })

  it('supports search flow', async () => {
    localStorage.setItem('vetstudy-token', token)
    global.fetch = vi.fn(async (url) => {
      const u = String(url)
      if (u.includes('/topics')) return { ok: true, json: async () => [{ id: '11111111-1111-1111-1111-111111111111', title: 'Surgery', subject_id: null }] }
      if (u.includes('/stats')) return { ok: true, json: async () => ({ topics_total: 1 }) }
      if (u.includes('/notes')) return { ok: true, json: async () => [{ id: 'n1', content: 'Old note', kind: 'note' }] }
      if (u.includes('/messages')) return { ok: true, json: async () => [] }
      if (u.includes('/flashcards')) return { ok: true, json: async () => [] }
      if (u.includes('/memory/search')) return { ok: true, json: async () => [{ id: 's1', content: 'Found item', kind: 'note' }] }
      if (u.includes('/admin/errors')) return { ok: true, json: async () => [{ id: 'e1', category: 'provider_timeout' }] }
      if (u.includes('/admin/feedback')) return { ok: true, json: async () => [{ id: 'f1', feedback_type: 'down', status: 'new' }] }
      if (u.includes('/admin/costs')) return { ok: true, json: async () => [{ user_id: 'u1', provider: 'mock', model: 'm1', calls: 1, cost_usd: 0.1 }] }
      if (u.includes('/topics/graph')) return { ok: true, json: async () => ({ nodes: [{ id: 'n1', title: 'Surgery' }], edges: [] }) }
      if (u.includes('/admin/evidence/source-coverage')) return { ok: true, json: async () => ({ missing: true }) }
      if (u.includes('/admin/evidence/needs-check')) return { ok: true, json: async () => [] }
      return { ok: true, json: async () => ({}) }
    })

    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    )

    const input = await screen.findByPlaceholderText('Search memory')
    await userEvent.type(input, 'Found')
    await userEvent.click(screen.getByText('Search'))

    await waitFor(() => expect(screen.getByText('Found item')).toBeInTheDocument())
  })

  it('renders review and admin screens', async () => {
    localStorage.setItem('vetstudy-token', token)
    global.fetch = vi.fn(async (url) => {
      const u = String(url)
      if (u.includes('/topics')) return { ok: true, json: async () => [{ id: '11111111-1111-1111-1111-111111111111', title: 'Surgery', subject_id: null }] }
      if (u.includes('/stats')) return { ok: true, json: async () => ({ topics_total: 1, due_flashcards: 1 }) }
      if (u.includes('/notes')) return { ok: true, json: async () => [] }
      if (u.includes('/messages')) return { ok: true, json: async () => [] }
      if (u.includes('/flashcards/')) return { ok: true, json: async () => ({}) }
      if (u.includes('/flashcards')) return { ok: true, json: async () => [{ id: 'c1', front: 'Q', back: 'A', interval_days: 1 }] }
      if (u.includes('/admin/errors')) return { ok: true, json: async () => [{ id: 'e1', category: 'provider_timeout' }] }
      if (u.includes('/admin/feedback')) return { ok: true, json: async () => [{ id: 'f1', feedback_type: 'down', status: 'new' }] }
      if (u.includes('/admin/costs')) return { ok: true, json: async () => [{ user_id: 'u1', provider: 'mock', model: 'm1', calls: 1, cost_cost: 0.1 }] }
      if (u.includes('/topics/graph')) return { ok: true, json: async () => ({ nodes: [{ id: 'n1', title: 'Surgery' }], edges: [] }) }
      if (u.includes('/admin/evidence/source-coverage')) return { ok: true, json: async () => ({ missing: true }) }
      if (u.includes('/admin/evidence/needs-check')) return { ok: true, json: async () => [] }
      return { ok: true, json: async () => ({}) }
    })
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    )
    await screen.findByText('VetStudy')
    await userEvent.click(screen.getByText('Review'))
    await screen.findByText('Ответ скрыт. Сначала раскройте карточку.')
    await userEvent.click(screen.getByText('Reveal'))
    await screen.findByText('A')
    await userEvent.click(screen.getByText('Admin'))
    await screen.findByText('Analytics & Health')
    await screen.findByText('Open negative feedback')
  })
})
