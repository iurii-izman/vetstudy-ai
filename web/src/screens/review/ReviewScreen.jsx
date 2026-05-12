import { EmptyState, LoadingState } from '../../shared/ui/States'
import { formatDate } from '../../shared/utils'

export function ReviewScreen({ cards, revealed, onReveal, onReview, loading }) {
  if (loading) return <LoadingState label="Loading review queue..." />
  if (!cards.length) return <EmptyState title="Нет карточек к повторению" detail="Сгенерируйте карточки через /cards, затем откройте review." />

  return (
    <div className="cards-grid review-grid" aria-label="Review queue">
      {cards.map((card) => (
        <article className="flashcard" key={card.id}>
          <header><span>Due {card.due_at ? formatDate(card.due_at) : 'now'}</span><strong>{card.interval_days || 0}d</strong></header>
          <h3>{card.front}</h3>
          {revealed[card.id] ? <p>{card.back}</p> : <p className="muted">Ответ скрыт. Сначала раскройте карточку.</p>}
          <div className="button-row">
            <button className="secondary-action" type="button" onClick={() => onReveal(card.id)}>Reveal</button>
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
