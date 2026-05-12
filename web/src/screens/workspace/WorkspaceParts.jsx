import * as React from 'react'
import { TagList } from '../../shared/ui/States'
import { cx, formatDate, shortId } from '../../shared/utils'

export function TopicButton({ topic, subject, active, onClick, counts }) {
  return (
    <button className={cx('topic-button', active && 'active')} type="button" onClick={onClick} aria-pressed={active}>
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

export function NoteEditor({ note, onCancel, onSave, busy }) {
  if (!note) return null
  return <NoteEditorForm key={note.id} note={note} onCancel={onCancel} onSave={onSave} busy={busy} />
}

function NoteEditorForm({ note, onCancel, onSave, busy }) {
  const [title, setTitle] = React.useState(note?.title || '')
  const [content, setContent] = React.useState(note?.content || '')
  const [tags, setTags] = React.useState((note?.tags || []).join(', '))

  const submit = (event) => {
    event.preventDefault()
    onSave({
      title: title.trim() || note.title || note.kind || 'Entry',
      content,
      tags: tags.split(',').map((item) => item.trim()).filter(Boolean),
    })
  }

  return (
    <form className="editor-panel" onSubmit={submit} aria-label="Edit note">
      <div className="panel-heading">
        <div>
          <h3>Edit memory item</h3>
          <p>{shortId(note.id)} · {note.kind}</p>
        </div>
        <button className="ghost-action" type="button" onClick={onCancel}>Close</button>
      </div>
      <label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} /></label>
      <label>Content<textarea rows={9} value={content} onChange={(event) => setContent(event.target.value)} /></label>
      <label>Tags<input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="drugs, risks, exam" /></label>
      <div className="button-row">
        <button className="primary-action" type="submit" disabled={busy || !content.trim()}>{busy ? 'Saving...' : 'Save'}</button>
        <button className="secondary-action" type="button" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}

export function MemoryList({ items, onEdit, sourceLabel }) {
  if (!items.length) return null
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
            <div className="row-footer"><TagList tags={item.tags || []} /><span>{formatDate(item.created_at)}</span></div>
          </div>
          {onEdit ? <button className="icon-action" type="button" onClick={() => onEdit(item)} aria-label="Edit note">Edit</button> : null}
        </article>
      ))}
    </div>
  )
}

export function MessageTimeline({ messages }) {
  if (!messages.length) return null
  return (
    <div className="timeline">
      {messages.map((message) => (
        <article className={cx('message-row', message.role)} key={message.id}>
          <div><span>{message.role}</span><time>{formatDate(message.created_at)}</time></div>
          <p>{message.content}</p>
        </article>
      ))}
    </div>
  )
}

export function FlashcardList({ cards, onReview }) {
  if (!cards.length) return null
  return (
    <div className="cards-grid">
      {cards.map((card) => (
        <article className="flashcard" key={card.id}>
          <header><span>Due {card.due_at ? formatDate(card.due_at) : 'now'}</span><strong>{card.interval_days || 0}d</strong></header>
          <h3>{card.front}</h3><p>{card.back}</p><TagList tags={card.tags || []} />
          <div className="button-row">
            <button className="secondary-action" type="button" onClick={() => onReview(card.id, 'again')}>Again</button>
            <button className="secondary-action" type="button" onClick={() => onReview(card.id, 'hard')}>Hard</button>
            <button className="primary-action" type="button" onClick={() => onReview(card.id, 'good')}>Good</button>
            <button className="primary-action" type="button" onClick={() => onReview(card.id, 'easy')}>Easy</button>
          </div>
        </article>
      ))}
    </div>
  )
}
