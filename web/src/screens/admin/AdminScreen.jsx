import { EmptyState, LoadingState } from '../../shared/ui/States'
import { formatDate } from '../../shared/utils'

export function AdminScreen({ feedback, analyticsSummary, learningExperiments, costBudgetAlert, stats, trustTrace, onUpdateFeedback, pendingFeedbackIds, loading }) {
  if (loading) return <LoadingState label="Loading admin dashboard..." />
  const openFeedback = feedback.filter((x) => x.feedback_type !== 'up' && x.status !== 'resolved' && x.status !== 'ignored')
  const highRiskCount = analyticsSummary?.behavior?.high_risk_query_count || 0
  const zeroResultSearches = analyticsSummary?.content_gap_report?.zero_results_total || 0
  const zeroByTopic = analyticsSummary?.content_gap_report?.zero_results_by_topic || {}
  const journeyHealth = analyticsSummary?.journey_health || {}
  const weakTopics = Object.entries(zeroByTopic).map(([t, c]) => `${t} (${c})`).join(', ') || 'None'
  const dropPoints = Object.entries(journeyHealth.drop_points || {})
  const dropPointsLabel = dropPoints.length ? dropPoints.map(([k, v]) => `${k} (${v})`).join(', ') : 'none'
  const budgetLevel = costBudgetAlert?.alert_level || 'unknown'
  const budgetTopModel = costBudgetAlert?.top_models?.[0]
  const budgetTopModelLabel = budgetTopModel ? `${budgetTopModel.provider}/${budgetTopModel.model}` : 'n/a'
  const learningKpis = learningExperiments?.kpis || {}
  const funnel = learningExperiments?.funnel || []
  const checkpointTable = learningExperiments?.checkpoint_table || []
  const comebackTable = learningExperiments?.comeback_table || []

  return (
    <section className="settings-view">
      <div className="settings-grid">
        <div className="settings-panel">
          <h2>Analytics & Health</h2>
          <dl><dt>Weak topics (zero results)</dt><dd>{weakTopics}</dd><dt>Due cards</dt><dd>{stats?.due_flashcards || 0}</dd><dt>High-risk count</dt><dd>{highRiskCount}</dd><dt>Zero-result searches</dt><dd>{zeroResultSearches}</dd></dl>
        </div>
        <div className="settings-panel">
          <h2>Journey Health</h2>
          <dl>
            <dt>Drop points</dt><dd>{dropPointsLabel}</dd>
            <dt>Recovery rate</dt><dd>{Math.round((journeyHealth.recovery_rate || 0) * 100)}%</dd>
            <dt>First-week completion</dt><dd>{Math.round((journeyHealth.first_week_completion_rate || 0) * 100)}%</dd>
            <dt>First value ≤10m</dt><dd>{Math.round((journeyHealth.first_value_10m_rate || 0) * 100)}%</dd>
          </dl>
        </div>
        <div className="settings-panel">
          <h2>Weekly Cost Budget</h2>
          <dl>
            <dt>Alert level</dt><dd>{budgetLevel}</dd>
            <dt>This week cost</dt><dd>${Number(costBudgetAlert?.cost_usd_current_week || 0).toFixed(4)}</dd>
            <dt>Budget</dt><dd>${Number(costBudgetAlert?.weekly_budget_usd || 0).toFixed(4)}</dd>
            <dt>Remaining</dt><dd>${Number(costBudgetAlert?.remaining_usd || 0).toFixed(4)}</dd>
            <dt>Top model</dt><dd>{budgetTopModelLabel}</dd>
          </dl>
        </div>
        <div className="settings-panel">
          <h2>Learning Experiments</h2>
          <dl>
            <dt>CTA step completion</dt><dd>{Math.round((learningKpis.cta_step_completion_rate || 0) * 100)}%</dd>
            <dt>Checkpoint completion</dt><dd>{Math.round((learningKpis.checkpoint_completion_rate || 0) * 100)}%</dd>
            <dt>Remediation completion</dt><dd>{Math.round((learningKpis.remediation_completion_rate || 0) * 100)}%</dd>
            <dt>Comeback success</dt><dd>{Math.round((learningKpis.comeback_success_rate || 0) * 100)}%</dd>
          </dl>
        </div>
        <div className="settings-panel wide">
          <h2>Learning Funnel</h2>
          <table>
            <thead><tr><th>step</th><th>count</th><th>users</th></tr></thead>
            <tbody>
              {funnel.map((row) => <tr key={row.step}><td>{row.step}</td><td>{row.count}</td><td>{row.users}</td></tr>)}
            </tbody>
          </table>
        </div>
        <div className="settings-panel wide">
          <h2>Checkpoint & Comeback</h2>
          <table>
            <thead><tr><th>metric</th><th>value</th><th>flow</th></tr></thead>
            <tbody>
              {checkpointTable.map((row) => <tr key={`cp-${row.metric}`}><td>{row.metric}</td><td>{row.count}</td><td>checkpoint</td></tr>)}
              {comebackTable.map((row) => <tr key={`cb-${row.metric}`}><td>{row.metric}</td><td>{row.count}</td><td>comeback</td></tr>)}
            </tbody>
          </table>
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
                <p><strong>trace:</strong> {item.trust_trace_compact || 'n/a'}</p>
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
