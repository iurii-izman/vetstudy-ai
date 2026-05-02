import { useCallback, useEffect, useMemo, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api } from './api'

const EMPTY_STATS = {
  topics_total: 0,
  sessions_total: 0,
  messages_total: 0,
  notes_total: 0,
  flashcards_total: 0,
  due_flashcards: 0,
}

function cx(...classes) {
  return classes.filter(Boolean).join(' ')
}

function formatDate(value) {
  if (!value) return 'n/a'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'n/a'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function shortId(value) {
  return value ? String(value).slice(0, 8) : 'none'
}

function Login({ onAuth }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const data = await api.login(password)
      onAuth(data.access_token)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form onSubmit={submit} className="login-card">
        <div className="brand-mark">VS</div>
        <h1>VetStudy AI Cabinet</h1>
        <p>Owner workspace for Telegram knowledge, cards, and topic control.</p>
        <label>
          Owner password
          <input
            autoFocus
            placeholder="Owner password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <button className="primary-action" type="submit" disabled={busy}>
          {busy ? 'Signing in...' : 'Sign in'}
        </button>
        {error ? <p className="error">{error}</p> : null}
      </form>
    </div>
  )
}

function TagList({ tags = [] }) {
  if (!tags.length) return <span className="tag muted-tag">no tags</span>
  return (
    <span className="tags">
      {tags.slice(0, 5).map((tag) => (
        <span className="tag" key={tag}>
          {tag}
        </span>
      ))}
    </span>
  )
}

function EmptyState({ title, detail }) {
  return (
    <div className="empty-state">
      <div className="empty-glyph" aria-hidden="true" />
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  )
}

function StatTile({ label, value, tone = 'neutral' }) {
  return (
    <div className={cx('stat-tile', tone)}>
      <span>{label}</span>
      <strong>{value ?? 0}</strong>
    </div>
  )
}

function TopicButton({ topic, subject, active, onClick, counts }) {
  return (
    <button className={cx('topic-button', active && 'active')} type="button" onClick={onClick}>
      <span>
        <strong>{topic.title}</strong>
        <small>{subject?.title || 'Без предмета'}</small>
      </span>
      <span className="topic-meta">
        <small>thread {topic.telegram_thread_id ?? 'main'}</small>
        <small>{counts.notes} notes</small>
      </span>
    </button>
  )
}

function NoteEditor({ note, onCancel, onSave, busy }) {
  const [title, setTitle] = useState(note?.title || '')
  const [content, setContent] = useState(note?.content || '')
  const [tags, setTags] = useState((note?.tags || []).join(', '))

  useEffect(() => {
    setTitle(note?.title || '')
    setContent(note?.content || '')
    setTags((note?.tags || []).join(', '))
  }, [note])

  if (!note) return null

  const submit = (event) => {
    event.preventDefault()
    onSave({
      title: title.trim() || note.title || note.kind || 'Entry',
      content,
      tags: tags
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
    })
  }

  return (
    <form className="editor-panel" onSubmit={submit}>
      <div className="panel-heading">
        <div>
          <h3>Edit memory item</h3>
          <p>{shortId(note.id)} · {note.kind}</p>
        </div>
        <button className="ghost-action" type="button" onClick={onCancel}>
          Close
        </button>
      </div>
      <label>
        Title
        <input value={title} onChange={(event) => setTitle(event.target.value)} />
      </label>
      <label>
        Content
        <textarea rows={9} value={content} onChange={(event) => setContent(event.target.value)} />
      </label>
      <label>
        Tags
        <input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="drugs, risks, exam" />
      </label>
      <div className="button-row">
        <button className="primary-action" type="submit" disabled={busy || !content.trim()}>
          {busy ? 'Saving...' : 'Save'}
        </button>
        <button className="secondary-action" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function MemoryList({ items, onEdit, sourceLabel }) {
  if (!items.length) {
    return <EmptyState title="Нет сохраненных фрагментов" detail="Ответы, заметки и результаты поиска появятся здесь после работы в Telegram." />
  }
  return (
    <div className="item-list">
      {items.map((item) => (
        <article className="memory-row" key={item.id}>
          <div className="row-main">
            <div className="row-title">
              <span className={cx('kind-chip', item.kind)}>{item.kind || sourceLabel}</span>
              <h3>{item.title || item.kind || 'Entry'}</h3>
            </div>
            <p>{item.content}</p>
            <div className="row-footer">
              <TagList tags={item.tags || []} />
              <span>{formatDate(item.created_at)}</span>
            </div>
          </div>
          {onEdit ? (
            <button className="icon-action" type="button" onClick={() => onEdit(item)} aria-label="Edit note">
              Edit
            </button>
          ) : null}
        </article>
      ))}
    </div>
  )
}

function MessageTimeline({ messages }) {
  if (!messages.length) {
    return <EmptyState title="Нет сообщений" detail="Диалог появится после первого вопроса в выбранном Telegram topic." />
  }
  return (
    <div className="timeline">
      {messages.map((message) => (
        <article className={cx('message-row', message.role)} key={message.id}>
          <div>
            <span>{message.role}</span>
            <time>{formatDate(message.created_at)}</time>
          </div>
          <p>{message.content}</p>
        </article>
      ))}
    </div>
  )
}

function FlashcardList({ cards }) {
  if (!cards.length) {
    return <EmptyState title="Нет карточек" detail="Создайте карточки кнопкой под ответом бота или командой /cards." />
  }
  return (
    <div className="cards-grid">
      {cards.map((card) => (
        <article className="flashcard" key={card.id}>
          <header>
            <span>Due {card.due_at ? formatDate(card.due_at) : 'now'}</span>
            <strong>{card.interval_days || 0}d</strong>
          </header>
          <h3>{card.front}</h3>
          <p>{card.back}</p>
          <TagList tags={card.tags || []} />
        </article>
      ))}
    </div>
  )
}

function Workspace({
  activePanel,
  setActivePanel,
  notes,
  messages,
  flashcards,
  searchResults,
  onEditNote,
  loadingTopic,
}) {
  const panelItems = [
    { id: 'memory', label: 'Memory', count: searchResults.length || notes.length },
    { id: 'dialog', label: 'Dialog', count: messages.length },
    { id: 'cards', label: 'Cards', count: flashcards.length },
  ]

  return (
    <section className="workspace">
      <div className="segmented-control" role="tablist" aria-label="Workspace panels">
        {panelItems.map((item) => (
          <button
            aria-selected={activePanel === item.id}
            className={activePanel === item.id ? 'active' : ''}
            key={item.id}
            onClick={() => setActivePanel(item.id)}
            role="tab"
            type="button"
          >
            {item.label}
            <span>{item.count}</span>
          </button>
        ))}
      </div>
      {loadingTopic ? <div className="loading-bar" /> : null}
      {activePanel === 'memory' ? (
        <MemoryList items={searchResults.length ? searchResults : notes} onEdit={searchResults.length ? null : onEditNote} sourceLabel="memory" />
      ) : null}
      {activePanel === 'dialog' ? <MessageTimeline messages={messages} /> : null}
      {activePanel === 'cards' ? <FlashcardList cards={flashcards} /> : null}
    </section>
  )
}

function SummaryView({ activeTopic, notes, messages, cards }) {
  return (
    <section className="summary-view">
      <div className="section-title">
        <h2>{activeTopic?.title || 'Topic summary'}</h2>
        <p>Thread {activeTopic?.telegram_thread_id ?? 'main'} · topic {shortId(activeTopic?.id)}</p>
      </div>
      <div className="summary-band">
        <p>{activeTopic?.summary || 'Summary is not generated yet. Use /summary in Telegram after a few answers are collected.'}</p>
      </div>
      <div className="summary-metrics">
        <StatTile label="Memory entries" value={notes.length} tone="blue" />
        <StatTile label="Messages" value={messages.length} tone="green" />
        <StatTile label="Cards" value={cards.length} tone="amber" />
      </div>
    </section>
  )
}

function SettingsView({ me, stats, subjects, modelSettings, onExport, onLogout, exportBusy }) {
  return (
    <section className="settings-view">
      <div className="settings-grid">
        <div className="settings-panel">
          <h2>Owner</h2>
          <dl>
            <dt>Telegram ID</dt>
            <dd>{me?.telegram_user_id || 'n/a'}</dd>
            <dt>Role</dt>
            <dd>{me?.role || 'n/a'}</dd>
            <dt>Language</dt>
            <dd>{me?.language || 'n/a'}</dd>
          </dl>
          <div className="button-row">
            <button className="primary-action" type="button" onClick={onExport} disabled={exportBusy}>
              {exportBusy ? 'Exporting...' : 'Export JSON'}
            </button>
            <button className="secondary-action danger" type="button" onClick={onLogout}>
              Sign out
            </button>
          </div>
        </div>
        <div className="settings-panel">
          <h2>AI routing</h2>
          <dl>
            <dt>Primary</dt>
            <dd>{modelSettings?.primary_provider || 'n/a'} · {modelSettings?.primary_model || 'n/a'}</dd>
            <dt>Fallback</dt>
            <dd>{modelSettings?.fallback_provider || 'n/a'} · {modelSettings?.fallback_model || 'n/a'}</dd>
            <dt>Max request</dt>
            <dd>{modelSettings?.max_request_tokens || 'n/a'} tokens</dd>
          </dl>
        </div>
        <div className="settings-panel wide">
          <h2>Subjects</h2>
          <div className="subject-strip">
            {subjects.map((subject) => (
              <span key={subject.id}>{subject.title}</span>
            ))}
          </div>
        </div>
      </div>
      <pre className="stats-json">{JSON.stringify(stats, null, 2)}</pre>
    </section>
  )
}

function Dashboard({ token, onLogout }) {
  const [topics, setTopics] = useState([])
  const [subjects, setSubjects] = useState([])
  const [activeTopic, setActiveTopic] = useState(null)
  const [notes, setNotes] = useState([])
  const [messages, setMessages] = useState([])
  const [flashcards, setFlashcards] = useState([])
  const [stats, setStats] = useState(EMPTY_STATS)
  const [me, setMe] = useState(null)
  const [modelSettings, setModelSettings] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [activePanel, setActivePanel] = useState('memory')
  const [editingNote, setEditingNote] = useState(null)
  const [error, setError] = useState('')
  const [loadingApp, setLoadingApp] = useState(true)
  const [loadingTopic, setLoadingTopic] = useState(false)
  const [savingNote, setSavingNote] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)

  const subjectMap = useMemo(() => new Map(subjects.map((subject) => [subject.id, subject])), [subjects])

  const countsByTopic = useMemo(() => {
    const map = new Map()
    for (const topic of topics) {
      map.set(topic.id, { notes: 0, cards: 0, messages: 0 })
    }
    for (const note of notes) {
      const key = note.topic_id
      map.set(key, { ...(map.get(key) || {}), notes: (map.get(key)?.notes || 0) + 1 })
    }
    return map
  }, [notes, topics])

  const loadShell = useCallback(async () => {
    setError('')
    setLoadingApp(true)
    try {
      const [topicsData, subjectsData, statsData, meData, modelData] = await Promise.all([
        api.topics(token),
        api.subjects(token).catch(() => []),
        api.stats(token).catch(() => EMPTY_STATS),
        api.me(token).catch(() => null),
        api.modelSettings(token).catch(() => null),
      ])
      const safeTopics = Array.isArray(topicsData) ? topicsData : []
      setTopics(safeTopics)
      setSubjects(Array.isArray(subjectsData) ? subjectsData : [])
      setStats({ ...EMPTY_STATS, ...(statsData || {}) })
      setMe(meData)
      setModelSettings(modelData)
      setActiveTopic((current) => current || safeTopics[0] || null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingApp(false)
    }
  }, [token])

  const loadTopic = useCallback(async () => {
    if (!activeTopic) {
      setNotes([])
      setMessages([])
      setFlashcards([])
      return
    }
    setError('')
    setLoadingTopic(true)
    try {
      const [notesData, messagesData, cardsData] = await Promise.all([
        api.notes(token, activeTopic.id),
        api.messages(token, activeTopic.id),
        api.flashcards(token, activeTopic.id),
      ])
      setNotes(Array.isArray(notesData) ? notesData : [])
      setMessages(Array.isArray(messagesData) ? messagesData : [])
      setFlashcards(Array.isArray(cardsData) ? cardsData : [])
      setSearchResults([])
      setEditingNote(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingTopic(false)
    }
  }, [activeTopic, token])

  useEffect(() => {
    loadShell()
  }, [loadShell])

  useEffect(() => {
    loadTopic()
  }, [loadTopic])

  const performSearch = async () => {
    const query = searchQuery.trim()
    if (!query) {
      setSearchResults([])
      return
    }
    setError('')
    setLoadingTopic(true)
    try {
      const data = await api.search(token, query, activeTopic?.id)
      setSearchResults(Array.isArray(data) ? data : [])
      setActivePanel('memory')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingTopic(false)
    }
  }

  const saveNote = async (payload) => {
    if (!editingNote) return
    setSavingNote(true)
    setError('')
    try {
      const updated = await api.updateNote(token, editingNote.id, payload)
      setNotes((items) => items.map((item) => (item.id === editingNote.id ? { ...item, ...updated } : item)))
      setEditingNote(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setSavingNote(false)
    }
  }

  const exportData = async () => {
    setExportBusy(true)
    setError('')
    try {
      const data = await api.exportData(token)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `vetstudy-export-${new Date().toISOString().slice(0, 10)}.json`
      anchor.style.display = 'none'
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err.message)
    } finally {
      setExportBusy(false)
    }
  }

  const clearSearch = () => {
    setSearchQuery('')
    setSearchResults([])
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-head">
          <div className="brand-mark">VS</div>
          <div>
            <h1>VetStudy</h1>
            <p>Telegram control room</p>
          </div>
        </div>
        <div className="topic-list">
          {topics.length ? (
            topics.map((topic) => (
              <TopicButton
                active={activeTopic?.id === topic.id}
                counts={countsByTopic.get(topic.id) || { notes: 0 }}
                key={topic.id}
                onClick={() => setActiveTopic(topic)}
                subject={subjectMap.get(topic.subject_id)}
                topic={topic}
              />
            ))
          ) : (
            <EmptyState title="Нет topic" detail="Проверьте /topics и /bind_topic в Telegram." />
          )}
        </div>
      </aside>
      <main className="content">
        <header className="topbar">
          <div className="topic-current">
            <span>Active topic</span>
            <h2>{activeTopic?.title || 'No topic selected'}</h2>
            <p>thread {activeTopic?.telegram_thread_id ?? 'main'} · {subjectMap.get(activeTopic?.subject_id)?.title || 'Без предмета'}</p>
          </div>
          <div className="search-box">
            <input
              placeholder="Search memory"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') performSearch()
                if (event.key === 'Escape') clearSearch()
              }}
            />
            <button className="primary-action" type="button" onClick={performSearch}>
              Search
            </button>
            <button className="secondary-action" type="button" onClick={clearSearch}>
              Clear
            </button>
          </div>
          <nav className="main-nav">
            <NavLink to="/">Workspace</NavLink>
            <NavLink to="/summary">Summary</NavLink>
            <NavLink to="/settings">Settings</NavLink>
          </nav>
        </header>

        <section className="status-strip" aria-label="Workspace status">
          <StatTile label="Topics" value={stats.topics_total} tone="blue" />
          <StatTile label="Messages" value={stats.messages_total} tone="green" />
          <StatTile label="Memory" value={stats.notes_total} tone="neutral" />
          <StatTile label="Due cards" value={stats.due_flashcards} tone="amber" />
        </section>

        {error ? (
          <div className="error-banner">
            <span>{error}</span>
            <button type="button" onClick={() => setError('')}>Dismiss</button>
          </div>
        ) : null}

        {loadingApp ? <div className="loading-bar" /> : null}

        <Routes>
          <Route
            path="/"
            element={
              <div className="workspace-grid">
                <Workspace
                  activePanel={activePanel}
                  flashcards={flashcards}
                  loadingTopic={loadingTopic}
                  messages={messages}
                  notes={notes}
                  onEditNote={setEditingNote}
                  searchResults={searchResults}
                  setActivePanel={setActivePanel}
                />
                <NoteEditor busy={savingNote} note={editingNote} onCancel={() => setEditingNote(null)} onSave={saveNote} />
              </div>
            }
          />
          <Route
            path="/summary"
            element={<SummaryView activeTopic={activeTopic} cards={flashcards} messages={messages} notes={notes} />}
          />
          <Route
            path="/settings"
            element={
              <SettingsView
                exportBusy={exportBusy}
                me={me}
                modelSettings={modelSettings}
                onExport={exportData}
                onLogout={onLogout}
                stats={stats}
                subjects={subjects}
              />
            }
          />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('vetstudy-token') || '')

  const handleAuth = (newToken) => {
    localStorage.setItem('vetstudy-token', newToken)
    setToken(newToken)
  }

  const handleLogout = () => {
    localStorage.removeItem('vetstudy-token')
    setToken('')
  }

  if (!token) return <Login onAuth={handleAuth} />

  return <Dashboard token={token} onLogout={handleLogout} />
}
