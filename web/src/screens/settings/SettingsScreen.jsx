import { EmptyState, LoadingState } from '../../shared/ui/States'

export function SettingsScreen({ me, modelSettings, coverage, needsCheck, onExport, onLogout, exportBusy, subjects, loading }) {
  if (loading) return <LoadingState label="Loading settings..." />

  const missingCoverage = coverage?.missing ? 'No source file found' : `${coverage?.total_sources || 0} sources loaded`
  const healthChecks = []
  if (needsCheck && needsCheck.length > 0) healthChecks.push(`${needsCheck.length} answers need manual check`)
  if (!coverage || coverage.missing || coverage.total_sources === 0) healthChecks.push('No evidence sources loaded')
  if (healthChecks.length === 0) healthChecks.push('All systems go')
  const healthStatus = healthChecks.join(' · ')

  return (
    <section className="settings-view">
      <div className="settings-grid">
        <div className="settings-panel">
          <h2>Owner</h2>
          <dl><dt>Telegram ID</dt><dd>{me?.telegram_user_id || 'n/a'}</dd><dt>Role</dt><dd>{me?.role || 'n/a'}</dd><dt>Language</dt><dd>{me?.language || 'n/a'}</dd><dt>Region</dt><dd>{me?.profile?.region || 'unspecified'}</dd><dt>Species focus</dt><dd>{me?.profile?.species_focus || 'dog_cat'}</dd></dl>
          <div className="button-row">
            <button className="primary-action" type="button" onClick={onExport} disabled={exportBusy}>{exportBusy ? 'Exporting...' : 'Export JSON'}</button>
            <button className="secondary-action danger" type="button" onClick={onLogout}>Sign out</button>
          </div>
        </div>
        <div className="settings-panel"><h2>System Health</h2><dl><dt>Go/No-Go Health</dt><dd>{healthStatus}</dd><dt>Source Coverage</dt><dd>{missingCoverage}</dd></dl></div>
        <div className="settings-panel"><h2>AI routing</h2><dl><dt>Primary</dt><dd>{modelSettings?.primary_provider || 'n/a'} · {modelSettings?.primary_model || 'n/a'}</dd><dt>Fallback</dt><dd>{modelSettings?.fallback_provider || 'n/a'} · {modelSettings?.fallback_model || 'n/a'}</dd><dt>Max request</dt><dd>{modelSettings?.max_request_tokens || 'n/a'} tokens</dd></dl></div>
        <div className="settings-panel wide">
          <h2>Subjects</h2>
          {!subjects.length ? <EmptyState title="No subjects" detail="Subjects will appear once Telegram topics are bound." /> : <div className="subject-strip">{subjects.map((subject) => <span key={subject.id}>{subject.title}</span>)}</div>}
        </div>
      </div>
    </section>
  )
}
