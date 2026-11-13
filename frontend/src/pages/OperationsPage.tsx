import { useState } from 'react'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Skeleton } from '@/components/ui'
import { v2Api, type AgentHealthDto } from '@/api/client'
import { PageHead } from './OverviewPage'
import { formatTime } from './format'
import { useAsync } from './useAsync'
import './pages.css'

function levelTone(level: string): 'allow' | 'approval' | 'warn' | 'critical' | 'neutral' {
  if (level === 'HIGH') return 'allow'
  if (level === 'MEDIUM') return 'approval'
  if (level === 'LOW') return 'warn'
  if (level === 'CRITICAL') return 'critical'
  return 'neutral'
}

export function OperationsPage() {
  const health = useAsync(() => v2Api.containmentAgents())
  const circuits = useAsync(() => v2Api.circuits())
  const notifications = useAsync(() => v2Api.notifications())
  const [busy, setBusy] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  async function act(key: string, operation: () => Promise<unknown>) {
    setBusy(key)
    setActionError(null)
    try {
      await operation()
      await Promise.all([health.reload(), circuits.reload(), notifications.reload()])
    } catch (caught) {
      setActionError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  function quarantine(agent: AgentHealthDto) {
    const reason = window.prompt(`Quarantine reason for ${agent.agent_name}`)
    if (!reason) return
    void act(`${agent.agent_id}:quarantine`, () => v2Api.quarantine(agent.agent_id, reason))
  }

  return (
    <div className="col" style={{ gap: 'var(--space-5)' }}>
      <PageHead
        title="Agent health"
        subtitle="Smoothed reliability, containment state, and circuit breakers. Reliability can add review friction; it never grants access or overrides an explicit DENY."
      />

      {actionError ? <div className="banner banner--error">{actionError}</div> : null}

      {health.loading ? (
        <Skeleton lines={6} height={20} />
      ) : health.error ? (
        <ErrorState message={health.error} onRetry={() => void health.reload()} />
      ) : !health.data?.length ? (
        <Card>
          <EmptyState
            title="No agents to evaluate"
            description="Register an agent and record workflow evidence to populate reliability and containment state."
          />
        </Card>
      ) : (
        <Card className="page-card">
          <CardHeader
            title="Reliability and containment"
            subtitle={`Method: each score is a weighted average of smoothed observed rates. INSUFFICIENT is reported below the observation threshold and never implies trust.`}
          />
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Operational</th>
                  <th>Reliability</th>
                  <th>Confidence</th>
                  <th>Observations</th>
                  <th>Circuit</th>
                  <th>Recent failures</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {health.data.map((agent) => (
                  <tr key={agent.agent_id}>
                    <td>
                      <div className="col" style={{ gap: 1 }}>
                        <span className="table__cell-main">{agent.agent_name}</span>
                        <span className="table__cell-sub mono">{agent.agent_id}</span>
                      </div>
                    </td>
                    <td>
                      <Badge
                        tone={
                          agent.operational_status === 'ACTIVE'
                            ? 'allow'
                            : agent.operational_status === 'QUARANTINED'
                              ? 'critical'
                              : 'warn'
                        }
                      >
                        {agent.operational_status}
                      </Badge>
                      {agent.quarantine_reason ? (
                        <div className="table__cell-sub">{agent.quarantine_reason}</div>
                      ) : null}
                    </td>
                    <td>
                      <div className="row" style={{ gap: 6 }}>
                        <Badge tone={levelTone(agent.reliability.level)}>
                          {agent.reliability.level}
                        </Badge>
                        <span className="mono">{agent.reliability.score.toFixed(1)}</span>
                      </div>
                      <div className="table__cell-sub">{agent.reliability.trend}</div>
                    </td>
                    <td className="mono">{agent.reliability.confidence.toFixed(2)}</td>
                    <td>{agent.reliability.observations}</td>
                    <td>
                      <Badge
                        tone={
                          agent.circuit_state === 'CLOSED'
                            ? 'allow'
                            : agent.circuit_state === 'HALF_OPEN'
                              ? 'approval'
                              : 'critical'
                        }
                      >
                        {agent.circuit_state}
                      </Badge>
                    </td>
                    <td>{agent.recent_failures}</td>
                    <td>
                      <div className="row" style={{ gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
                        {agent.operational_status === 'QUARANTINED' ? (
                          <Button
                            variant="success"
                            size="sm"
                            loading={busy === `${agent.agent_id}:recover`}
                            onClick={() =>
                              void act(`${agent.agent_id}:recover`, () =>
                                v2Api.startRecovery(agent.agent_id),
                              )
                            }
                          >
                            Start recovery
                          </Button>
                        ) : null}
                        {agent.operational_status === 'RECOVERING' ? (
                          <Button
                            variant="success"
                            size="sm"
                            loading={busy === `${agent.agent_id}:release`}
                            onClick={() =>
                              void act(`${agent.agent_id}:release`, () =>
                                v2Api.completeRecovery(agent.agent_id),
                              )
                            }
                          >
                            Complete recovery
                          </Button>
                        ) : null}
                        {agent.operational_status === 'ACTIVE' ? (
                          <Button
                            variant="danger"
                            size="sm"
                            loading={busy === `${agent.agent_id}:quarantine`}
                            onClick={() => quarantine(agent)}
                          >
                            Quarantine
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

      <div className="grid-2">
        <Card>
          <CardHeader title="Circuit breakers" subtitle="Open circuits fail closed until the cooldown permits a half-open trial." />
          {circuits.loading ? (
            <Skeleton lines={3} />
          ) : circuits.error ? (
            <ErrorState message={circuits.error} onRetry={() => void circuits.reload()} />
          ) : (circuits.data ?? []).length === 0 ? (
            <p className="muted">No circuit has been opened.</p>
          ) : (
            <ul className="item-list">
              {(circuits.data ?? []).map((row) => (
                <li key={String(row.id)}>
                  <div className="item-row">
                    <div className="grow col" style={{ gap: 1 }}>
                      <span className="item-row__title">{String(row.tool_name)}</span>
                      <span className="item-row__sub mono">{String(row.agent_id)}</span>
                    </div>
                    <Badge tone={row.state === 'OPEN' ? 'critical' : row.state === 'HALF_OPEN' ? 'approval' : 'allow'}>
                      {String(row.state)}
                    </Badge>
                    <span className="muted">{String(row.failure_count)} failures</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader title="Notifications" subtitle="Containment and incident alerts generated by the control plane." />
          {notifications.loading ? (
            <Skeleton lines={3} />
          ) : notifications.error ? (
            <ErrorState message={notifications.error} onRetry={() => void notifications.reload()} />
          ) : (notifications.data ?? []).length === 0 ? (
            <p className="muted">No notifications.</p>
          ) : (
            <ul className="item-list">
              {(notifications.data ?? []).slice(0, 8).map((row) => (
                <li key={String(row.id)}>
                  <div className="item-row">
                    <div className="grow col" style={{ gap: 1 }}>
                      <span className="item-row__title">{String(row.title)}</span>
                      <span className="item-row__sub">{String(row.body)}</span>
                    </div>
                    <span className="muted">{formatTime(String(row.created_at))}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}
