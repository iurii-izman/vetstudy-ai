import { EmptyState, LoadingState } from '../../shared/ui/States'
import { formatDate } from '../../shared/utils'

export function AdminScreen({ feedback, analyticsSummary, stats, trustTrace, onUpdateFeedback, pendingFeedbackIds, loading }) {
  if (loading) return <LoadingState label="Loading admin dashboard..." />
  const openFeedback = feedback.filter((x) => x.feedback_type !== 'up' && x.status !== 'resolved' && x.status !== 'ignored')
  const highRiskCount = analyticsSummary?.behavior?.high_risk_query_count || 0
  const zeroResultSearches = analyticsSummary?.content_gap_report?.zero_results_total || 0
  const zeroByTopic = analyticsSummary?.content_gap_report?.zero_results_by_topic || {}
  const weakTopics = Object.entries(zeroByTopic).map(([t, c]) => `${t} (${c})`).join(', ') || 'None'

  return (
    <section className="settings-view">
      <div className="settings-grid">
        <div className="settings-panel">
          <h2>Analytics & Health</h2>
          <dl><dt>Weak topics (zero results)</dt><dd>{weakTopics}</dd><dt>Due cards</dt><dd>{stats?.due_flashcards || 0}</dd><dt>High-risk count</dt><dd>{highRiskCount}</dd><dt>Zero-result searches</dt><dd>{zeroResultSearches}</dd></dl>
        </div>
        <div className="settings-panel wide">
          <h2>Trust &amp; Safety trace</h2>
          <div className="timeline">
            {!trustTrace?.length ? <EmptyState title="No recent high-risk traces" detail="High-risk assistant answers will appear here." /> : null}
            {(trustTrace || []).map((item) => (
              <article className="message-row assistant" key={item.message_id}>
                <div><span>{item.risk_intent || 'unknown_intent'}</span><time>{formatDate(item.created_at)}</time></div>
                <p>{item.preview || 'No preview.'}</p>
                <p><strong>tags:</strong> {(item.risk_tags || []).join(', ') || 'none'}</p>
                <p><strong>trust:</strong> {(item.trust_indicators || []).join(' · ') || 'n/a'}</p>
                <p><strong>verify:</strong> {item.verification_status || 'unknown'} | <strong>manual:</strong> {item.needs_manual_check ? 'yes' : 'no'}</p>
              </article>
            ))}
          </div>
        </div>
        <div className="settings-panel wide">
          <h2>Open negative feedback</h2>
          <div className="timeline">
            {!openFeedback.length ? <EmptyState title="No open negative feedback" detail="All negative feedback items are already triaged." /> : null}
            {openFeedback.map((item) => (
              <article className="message-row user" key={item.id}>
                <div><span>{item.feedback_type}</span><time>{formatDate(item.created_at)}</time></div>
                <p>{item.details || 'No details provided.'}</p>
                <div className="button-row" style={{ marginTop: '8px' }}>
                  {['new', 'in_review', 'resolved', 'ignored'].map((st) => (
                    <button key={st} type="button" className={item.status === st ? 'primary-action' : 'secondary-action'} onClick={() => onUpdateFeedback(item.id, st)} disabled={pendingFeedbackIds.includes(item.id)}>
                      {st.replace('_', ' ')}
                    </button>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
