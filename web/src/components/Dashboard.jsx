import { useCallback, useEffect, useMemo, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api } from '../api'
import { AdminScreen } from '../screens/admin/AdminScreen'
import { ReviewScreen } from '../screens/review/ReviewScreen'
import { SettingsScreen } from '../screens/settings/SettingsScreen'
import { WorkspaceScreen } from '../screens/workspace/WorkspaceScreen'
import { NoteEditor, TopicButton } from '../screens/workspace/WorkspaceParts'
import { ErrorState, LoadingState, StatTile } from '../shared/ui/States'

const EMPTY_STATS = { topics_total: 0, sessions_total: 0, messages_total: 0, notes_total: 0, flashcards_total: 0, due_flashcards: 0 }

export function Dashboard({ token, onLogout }) {
  const [topics, setTopics] = useState([])
  const [subjects, setSubjects] = useState([])
  const [activeTopic, setActiveTopic] = useState(null)
  const [notes, setNotes] = useState([])
  const [messages, setMessages] = useState([])
  const [flashcards, setFlashcards] = useState([])
  const [stats, setStats] = useState(EMPTY_STATS)
  const [me, setMe] = useState(null)
  const [modelSettings, setModelSettings] = useState(null)
  const [adminErrors, setAdminErrors] = useState([])
  const [adminFeedback, setAdminFeedback] = useState([])
  const [analyticsSummary, setAnalyticsSummary] = useState({})
  const [costBudgetAlert, setCostBudgetAlert] = useState(null)
  const [coverage, setCoverage] = useState(null)
  const [needsCheck, setNeedsCheck] = useState([])
  const [trustTrace, setTrustTrace] = useState([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchFacets, setSearchFacets] = useState({ kind: '', tag: '', dateFrom: '', dateTo: '' })
  const [searchResults, setSearchResults] = useState([])
  const [revealedCards, setRevealedCards] = useState({})
  const [activePanel, setActivePanel] = useState('memory')
  const [editingNote, setEditingNote] = useState(null)
  const [error, setError] = useState('')
  const [loadingApp, setLoadingApp] = useState(true)
  const [loadingTopic, setLoadingTopic] = useState(false)
  const [savingNote, setSavingNote] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const [pendingFeedbackIds, setPendingFeedbackIds] = useState([])

  const subjectMap = useMemo(() => new Map(subjects.map((subject) => [subject.id, subject])), [subjects])
  const countsByTopic = useMemo(() => {
    const map = new Map(topics.map((topic) => [topic.id, { notes: 0, cards: 0, messages: 0 }]))
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
      const [topicsData, subjectsData, statsData, meData, modelData, errorsData, feedbackData, analyticsData, costAlertData, coverageData, checkData, traceData] = await Promise.all([
        api.topics(token), api.subjects(token).catch(() => []), api.stats(token).catch(() => EMPTY_STATS), api.me(token).catch(() => null),
        api.modelSettings(token).catch(() => null), api.adminErrors(token).catch(() => []), api.adminFeedback(token).catch(() => []), api.adminAnalyticsSummary(token).catch(() => ({})),
        api.adminCostBudgetAlert(token).catch(() => null),
        api.sourceCoverage(token).catch(() => null), api.needsCheck(token).catch(() => []),
        api.trustSafetyTrace(token).catch(() => []),
      ])
      const safeTopics = Array.isArray(topicsData) ? topicsData : []
      setTopics(safeTopics)
      setSubjects(subjectsData)
      setStats({ ...EMPTY_STATS, ...(statsData || {}) })
      setMe(meData)
      setModelSettings(modelData)
      setAdminErrors(errorsData)
      setAdminFeedback(feedbackData)
      setAnalyticsSummary(analyticsData || {})
      setCostBudgetAlert(costAlertData)
      setCoverage(coverageData)
      setNeedsCheck(checkData)
      setTrustTrace(traceData)
      setActiveTopic((current) => current || safeTopics[0] || null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingApp(false)
    }
  }, [token])

  const loadTopic = useCallback(async () => {
    if (!activeTopic) {
      setNotes([]); setMessages([]); setFlashcards([])
      return
    }
    setError('')
    setLoadingTopic(true)
    try {
      const [notesData, messagesData, cardsData] = await Promise.all([
        api.notes(token, activeTopic.id), api.messages(token, activeTopic.id), api.flashcards(token, activeTopic.id),
      ])
      setNotes(notesData)
      setMessages(messagesData)
      setFlashcards(cardsData)
      setSearchResults([])
      setEditingNote(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingTopic(false)
    }
  }, [activeTopic, token])

  useEffect(() => { loadShell() }, [loadShell])
  useEffect(() => { loadTopic() }, [loadTopic])

  const performSearch = async () => {
    const query = searchQuery.trim()
    if (!query) { setSearchResults([]); return }
    setError(''); setLoadingTopic(true)
    try {
      const data = await api.search(token, query, activeTopic?.id, searchFacets)
      setSearchResults(data)
      setActivePanel('memory')
    } catch (err) { setError(err.message) } finally { setLoadingTopic(false) }
  }

  const saveNote = async (payload) => {
    if (!editingNote) return
    setSavingNote(true); setError('')
    try {
      const updated = await api.updateNote(token, editingNote.id, payload)
      setNotes((items) => items.map((item) => (item.id === editingNote.id ? { ...item, ...updated } : item)))
      setEditingNote(null)
    } catch (err) { setError(err.message) } finally { setSavingNote(false) }
  }

  const reviewCard = async (cardId, action) => {
    try {
      await api.reviewFlashcard(token, cardId, action)
      setRevealedCards((prev) => { const copy = { ...prev }; delete copy[cardId]; return copy })
      await loadTopic()
    } catch (err) { setError(err.message) }
  }

  const exportData = async () => {
    setExportBusy(true); setError('')
    try {
      const data = await api.exportData(token)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = `vetstudy-export-${new Date().toISOString().slice(0, 10)}.json`; anchor.style.display = 'none'
      document.body.appendChild(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(url)
    } catch (err) { setError(err.message) } finally { setExportBusy(false) }
  }

  const updateFeedbackStatus = async (id, status) => {
    const previous = adminFeedback
    setPendingFeedbackIds((prev) => [...prev, id])
    setAdminFeedback((prev) => prev.map((f) => (f.id === id ? { ...f, status } : f)))
    try {
      const updated = await api.updateFeedback(token, id, { status })
      setAdminFeedback((prev) => prev.map((f) => (f.id === id ? { ...f, status: updated.status } : f)))
    } catch (err) {
      setAdminFeedback(previous)
      setError(err.message)
    } finally {
      setPendingFeedbackIds((prev) => prev.filter((item) => item !== id))
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Topics sidebar">
        <div className="sidebar-head"><div className="brand-mark">VS</div><div><h1>VetStudy</h1><p>Telegram control room</p></div></div>
        <div className="topic-list" role="listbox" aria-label="Topics list">
          {topics.length ? topics.map((topic) => <TopicButton active={activeTopic?.id === topic.id} counts={countsByTopic.get(topic.id) || { notes: 0 }} key={topic.id} onClick={() => setActiveTopic(topic)} subject={subjectMap.get(topic.subject_id)} topic={topic} />) : <p className="muted">No topics yet.</p>}
        </div>
      </aside>
      <main className="content">
        <header className="topbar">
          <div className="topic-current"><span>Active topic</span><h2>{activeTopic?.title || 'No topic selected'}</h2><p>thread {activeTopic?.telegram_thread_id ?? 'main'} · {subjectMap.get(activeTopic?.subject_id)?.title || 'Без предмета'}</p></div>
          <div className="search-box">
            <input aria-label="Search memory" placeholder="Search memory" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') performSearch(); if (event.key === 'Escape') { setSearchQuery(''); setSearchResults([]) } }} />
            <button className="primary-action" type="button" onClick={performSearch}>Search</button>
            <button className="secondary-action" type="button" onClick={() => { setSearchQuery(''); setSearchResults([]); setSearchFacets({ kind: '', tag: '', dateFrom: '', dateTo: '' }) }}>Clear</button>
            <input placeholder="kind" aria-label="kind" value={searchFacets.kind} onChange={(event) => setSearchFacets((prev) => ({ ...prev, kind: event.target.value }))} />
            <input placeholder="tag" aria-label="tag" value={searchFacets.tag} onChange={(event) => setSearchFacets((prev) => ({ ...prev, tag: event.target.value }))} />
          </div>
          <nav className="main-nav" aria-label="Main navigation"><NavLink to="/">Workspace</NavLink><NavLink to="/review">Review</NavLink><NavLink to="/admin">Admin</NavLink><NavLink to="/settings">Settings</NavLink></nav>
        </header>

        <section className="status-strip" aria-label="Workspace status"><StatTile label="Topics" value={stats.topics_total} tone="blue" /><StatTile label="Messages" value={stats.messages_total} tone="green" /><StatTile label="Memory" value={stats.notes_total} tone="neutral" /><StatTile label="Due cards" value={stats.due_flashcards} tone="amber" /></section>
        <section className="status-strip" aria-label="Admin status"><StatTile label="Errors" value={adminErrors.length} tone="amber" /><StatTile label="Feedback↓" value={adminFeedback.filter((x) => x.feedback_type !== 'up').length} tone="blue" /><StatTile label="Feedback↑" value={adminFeedback.filter((x) => x.feedback_type === 'up').length} tone="green" /><StatTile label="All feedback" value={adminFeedback.length} tone="neutral" /></section>

        <ErrorState error={error} onRetry={loadShell} />
        {loadingApp ? <LoadingState label="Loading workspace shell..." /> : null}

        <Routes>
          <Route path="/" element={<div className="workspace-grid"><WorkspaceScreen activePanel={activePanel} flashcards={flashcards} loadingTopic={loadingTopic} messages={messages} notes={notes} onEditNote={setEditingNote} searchResults={searchResults} setActivePanel={setActivePanel} onReviewCard={reviewCard} /><NoteEditor busy={savingNote} note={editingNote} onCancel={() => setEditingNote(null)} onSave={saveNote} /></div>} />
          <Route path="/review" element={<ReviewScreen cards={flashcards} revealed={revealedCards} onReveal={(cardId) => setRevealedCards((prev) => ({ ...prev, [cardId]: true }))} onReview={reviewCard} loading={loadingTopic} />} />
          <Route path="/admin" element={<AdminScreen feedback={adminFeedback} analyticsSummary={analyticsSummary} costBudgetAlert={costBudgetAlert} stats={stats} trustTrace={trustTrace} onUpdateFeedback={updateFeedbackStatus} pendingFeedbackIds={pendingFeedbackIds} loading={loadingApp} />} />
          <Route path="/settings" element={<SettingsScreen exportBusy={exportBusy} me={me} modelSettings={modelSettings} coverage={coverage} needsCheck={needsCheck} onExport={exportData} onLogout={onLogout} subjects={subjects} loading={loadingApp} />} />
        </Routes>
      </main>
    </div>
  )
}
