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
})
