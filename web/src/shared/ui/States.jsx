import { cx } from '../utils'

export function EmptyState({ title, detail }) {
  return (
    <div className="empty-state" role="status" aria-live="polite">
      <div className="empty-glyph" aria-hidden="true" />
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  )
}

export function LoadingState({ label = 'Loading...' }) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <div className="loading-bar" />
      <p>{label}</p>
    </div>
  )
}

export function ErrorState({ error, onRetry }) {
  if (!error) return null
  return (
    <div className="error-banner" role="alert">
      <span>{error}</span>
      {onRetry ? <button type="button" onClick={onRetry}>Retry</button> : null}
    </div>
  )
}

export function StatTile({ label, value, tone = 'neutral' }) {
  return (
    <div className={cx('stat-tile', tone)}>
      <span>{label}</span>
      <strong>{value ?? 0}</strong>
    </div>
  )
}

export function TagList({ tags = [] }) {
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
