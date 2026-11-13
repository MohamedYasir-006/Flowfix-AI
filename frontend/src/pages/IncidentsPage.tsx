import { useState } from 'react'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Field, Skeleton } from '@/components/ui'
import { v2Api, type IncidentDto, type IncidentReportDto } from '@/api/client'
import { PageHead } from './OverviewPage'
import { formatTime } from './format'
import { useAsync } from './useAsync'
import './pages.css'

function riskTone(level: string): 'allow' | 'approval' | 'warn' | 'critical' {
  if (level === 'LOW') return 'allow'
  if (level === 'MEDIUM') return 'approval'
  return level === 'HIGH' ? 'warn' : 'critical'
}

export function IncidentsPage() {
  const [status, setStatus] = useState('')
  const incidents = useAsync(() => v2Api.incidents(status || undefined), [status])
  const [report, setReport] = useState<IncidentReportDto | null>(null)
  const [reportError, setReportError] = useState<string | null>(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)

  const [actionId, setActionId] = useState('')
  const [hypothetical, setHypothetical] = useState('ALLOW')
  const [whatIfResult, setWhatIfResult] = useState<Record<string, unknown> | null>(null)
  const [whatIfError, setWhatIfError] = useState<string | null>(null)

  async function openReport(incident: IncidentDto) {
    setReportLoading(true)
    setReportError(null)
    try {
      setReport(await v2Api.incidentReport(incident.id))
    } catch (caught) {
      setReportError((caught as Error).message)
    } finally {
      setReportLoading(false)
    }
  }

  async function resolve(incident: IncidentDto) {
    const resolution = window.prompt('Resolution note')
    if (resolution === null) return
    setBusy(incident.id)
    try {
      await v2Api.resolveIncident(incident.id, resolution)
      await incidents.reload()
      if (report?.incident.id === incident.id) await openReport(incident)
    } finally {
      setBusy(null)
    }
  }

  async function simulate() {
    setWhatIfError(null)
    setWhatIfResult(null)
    try {
      setWhatIfResult(await v2Api.whatIf(actionId.trim(), hypothetical))
    } catch (caught) {
      setWhatIfError((caught as Error).message)
    }
  }

  return (
    <div className="col" style={{ gap: 'var(--space-5)' }}>
      <PageHead
        title="Incidents and replay"
        subtitle="Incidents preserve the recorded evidence behind a propagation denial. Replay is reconstructed from stored events; it never re-executes an external action."
        action={
          <select className="select" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">All statuses</option>
            <option value="OPEN">Open</option>
            <option value="RESOLVED">Resolved</option>
          </select>
        }
      />

      {incidents.loading ? (
        <Skeleton lines={6} height={20} />
      ) : incidents.error ? (
        <ErrorState message={incidents.error} onRetry={() => void incidents.reload()} />
      ) : !incidents.data?.length ? (
        <Card>
          <EmptyState
            title="No incidents"
            description="A deterministic propagation denial inside a workflow creates an incident with origin and blast-radius evidence."
          />
        </Card>
      ) : (
        <Card className="page-card">
          <CardHeader title="Incident queue" subtitle={`${incidents.data.length} recorded incident(s)`} />
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Incident</th>
                  <th>Failure</th>
                  <th>Risk</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {incidents.data.map((incident) => (
                  <tr key={incident.id}>
                    <td>
                      <div className="col" style={{ gap: 1 }}>
                        <span className="table__cell-main">{incident.summary}</span>
                        <span className="table__cell-sub mono">{incident.id}</span>
                      </div>
                    </td>
                    <td className="mono">{incident.failure_type}</td>
                    <td>
                      <Badge tone={riskTone(incident.risk_level)}>{incident.risk_level}</Badge>
                    </td>
                    <td>
                      <Badge tone={incident.status === 'OPEN' ? 'critical' : 'allow'}>
                        {incident.status}
                      </Badge>
                    </td>
                    <td className="muted">{formatTime(incident.created_at)}</td>
                    <td>
                      <div className="row" style={{ gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
                        <Button variant="ghost" size="sm" onClick={() => void openReport(incident)}>
                          Open replay
                        </Button>
                        {incident.status === 'OPEN' ? (
                          <Button
                            variant="success"
                            size="sm"
                            loading={busy === incident.id}
                            onClick={() => void resolve(incident)}
                          >
                            Resolve
                          </Button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {reportLoading ? <Skeleton lines={4} /> : null}
      {reportError ? <div className="banner banner--error">{reportError}</div> : null}
      {report ? (
        <div className="grid-2">
          <Card>
            <CardHeader title="Replay timeline" subtitle={report.incident.summary} />
            <ul className="event-list event-list--divided">
              {report.timeline.map((entry, index) => (
                <li key={`${entry.timestamp}-${index}`}>
                  <div className="event-row">
                    <div className="grow col" style={{ gap: 1 }}>
                      <span className="item-row__title">{entry.summary}</span>
                      <span className="item-row__sub">
                        {entry.kind}
                        {entry.actor ? ` · ${entry.actor}` : ''}
                      </span>
                    </div>
                    <span className="event-row__time muted">{formatTime(entry.timestamp)}</span>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <CardHeader title="Impact and recommendation" />
            <div className="detail-grid">
              <div className="detail">
                <span className="detail__label">Affected agents</span>
                <span className="detail__value mono">
                  {report.affected_agents.join(', ') || 'none recorded'}
                </span>
              </div>
              <div className="detail">
                <span className="detail__label">Affected workflows</span>
                <span className="detail__value mono">
                  {report.affected_workflows.join(', ') || 'none recorded'}
                </span>
              </div>
            </div>
            <p className="muted">{report.recommendation}</p>
            <h3 style={{ marginTop: 'var(--space-4)' }}>What-if simulation</h3>
            <p className="muted" style={{ fontSize: 13 }}>
              Read-only. Uses the recorded action evidence and never invokes a tool.
            </p>
            <div className="col" style={{ gap: 'var(--space-3)', marginTop: 'var(--space-3)' }}>
              <Field label="Action ID" htmlFor="what-if-action">
                <input
                  id="what-if-action"
                  className="input"
                  value={actionId}
                  onChange={(event) => setActionId(event.target.value)}
                  placeholder="action id from the timeline"
                />
              </Field>
              <Field label="Hypothetical decision" htmlFor="what-if-decision">
                <select
                  id="what-if-decision"
                  className="select"
                  value={hypothetical}
                  onChange={(event) => setHypothetical(event.target.value)}
                >
                  <option value="ALLOW">ALLOW</option>
                  <option value="DENY">DENY</option>
                  <option value="REQUIRE_APPROVAL">REQUIRE_APPROVAL</option>
                </select>
              </Field>
              <Button variant="primary" disabled={!actionId.trim()} onClick={() => void simulate()}>
                Simulate
              </Button>
              {whatIfError ? <div className="banner banner--error">{whatIfError}</div> : null}
              {whatIfResult ? (
                <div className="col" style={{ gap: 4 }}>
                  <Badge tone="info">{String(whatIfResult.hypothetical_effect)}</Badge>
                  <span className="muted" style={{ fontSize: 13 }}>
                    Actual decision: {String(whatIfResult.actual_decision)}
                  </span>
                  <span className="muted" style={{ fontSize: 13 }}>
                    {String(whatIfResult.note)}
                  </span>
                </div>
              ) : null}
            </div>
          </Card>
        </div>
      ) : null}
    </div>
  )
}
