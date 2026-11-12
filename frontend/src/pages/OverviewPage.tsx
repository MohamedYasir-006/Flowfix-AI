import { Link } from 'react-router-dom'
import { useData } from '@/api/DataContext'
import {
  Badge,
  Card,
  CardHeader,
  DecisionBadge,
  EmptyState,
  ErrorState,
  RiskBadge,
  Skeleton,
} from '@/components/ui'
import type { AuditEvent } from '@/types'
import { formatTime } from './format'
import './pages.css'

export function OverviewPage() {
  const { overview, loading, error, refresh, agents, approvals } = useData()

  if (loading && !overview) {
    return (
      <div className="col" style={{ gap: 'var(--space-5)' }}>
        <PageHead
          title="Overview"
          subtitle="Live view of agent activity, enforcement, and items needing attention."
        />
        <Skeleton lines={6} height={22} />
      </div>
    )
  }

  if (error && !overview) {
    return <ErrorState message={error} onRetry={() => void refresh()} />
  }

  if (!overview) return null

  const stats = [
    { label: 'Active agents', value: overview.activeAgents, sub: `${overview.totalAgents} registered total`, tone: '' },
    { label: 'Actions today', value: overview.actionsToday, sub: 'intercepted by the policy engine', tone: '' },
    { label: 'Blocked today', value: overview.blockedToday, sub: 'denied before tool execution', tone: 'deny' },
    { label: 'Pending approvals', value: overview.pendingApprovals, sub: 'awaiting an authorized approver', tone: 'approval' },
  ]

  const pending = approvals.filter((a) => a.status === 'PENDING')
  const attention = pending.slice(0, 4)
  const activeAgents = agents.filter((a) => a.status === 'ACTIVE')

  return (
    <div className="col" style={{ gap: 'var(--space-5)' }}>
      <PageHead
        title="Overview"
        subtitle="Live view of agent activity, enforcement, and items needing attention."
        action={
          <Link to="/activity" className="btn btn--secondary btn--sm">
            View all activity
          </Link>
        }
      />

      <section className="stat-grid" aria-label="Key metrics">
        {stats.map((s) => (
          <div key={s.label} className={`stat ${s.tone ? `stat--${s.tone}` : ''}`}>
            <span className="stat__label">{s.label}</span>
            <span className="stat__value">{s.value}</span>
            <span className="stat__delta">{s.sub}</span>
          </div>
        ))}
      </section>

      <div className="grid-2">
        <Card>
          <CardHeader
            title="Needs attention"
            subtitle="Protected actions waiting on a human decision. Nothing executes until approved."
            action={
              <Link to="/approvals" className="btn btn--ghost btn--sm">
                Open queue
              </Link>
            }
          />
          {attention.length === 0 ? (
            <EmptyState
              title="No pending approvals"
              description="Actions that require human review will appear here."
            />
          ) : (
            <ul className="item-list">
              {attention.map((a) => (
                <li key={a.id}>
                  <Link to="/approvals" className="item-row">
                    <div className="grow col" style={{ gap: 2 }}>
                      <span className="item-row__title mono">{a.toolName}</span>
                      <span className="item-row__sub">
                        {agentName(agents, a.requestedByAgentId)} → {a.target}
                      </span>
                    </div>
                    <RiskBadge level={a.riskLevel} />
                    <Badge tone="approval">Pending</Badge>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader
            title="Agent status"
            subtitle="Registered agents and their current enforcement state."
            action={
              <Link to="/agents" className="btn btn--ghost btn--sm">
                Manage agents
              </Link>
            }
          />
          {activeAgents.length === 0 ? (
            <EmptyState title="No active agents" description="Register an agent to start governing its tool calls." />
          ) : (
            <ul className="item-list">
              {activeAgents.map((a) => (
                <li key={a.id}>
                  <Link to="/agents" className="item-row">
                    <span className={`status-dot ${a.status === 'ACTIVE' ? 'status-dot--on' : 'status-dot--off'}`} />
                    <div className="grow col" style={{ gap: 2 }}>
                      <span className="item-row__title">{a.name}</span>
                      <span className="item-row__sub">
                        {a.toolIds.length} tool{a.toolIds.length === 1 ? '' : 's'} · {a.environment}
                      </span>
                    </div>
                    <Badge tone="neutral">{a.environment}</Badge>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Recent decisions"
          subtitle="The latest policy decisions across all agents, including the reason for each outcome."
          action={
            <Link to="/activity" className="btn btn--ghost btn--sm">
              Activity log
            </Link>
          }
        />
        {overview.recentEvents.length === 0 ? (
          <EmptyState title="No activity yet" description="Policy decisions will appear here as agents make tool calls." />
        ) : (
          <ul className="event-list">
            {overview.recentEvents.map((e) => (
              <EventRow key={e.id} event={e} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}

export function EventRow({ event }: { event: AuditEvent }) {
  return (
    <li className="event-row">
      <div className="event-row__icon" aria-hidden>
        {event.eventType === 'decision' || event.eventType === 'execution' ? (
          event.decision ? (
            <DecisionBadge decision={event.decision} />
          ) : (
            <Badge tone="info">Executed</Badge>
          )
        ) : event.eventType === 'approval' ? (
          <Badge tone="approval">Approval</Badge>
        ) : (
          <Badge tone="neutral">Admin</Badge>
        )}
      </div>
      <div className="grow col" style={{ gap: 2 }}>
        <span className="item-row__title">
          {event.toolName ?? event.agentName ?? 'System event'}
          {event.agentName && event.toolName ? (
            <span className="item-row__sub"> · {event.agentName}</span>
          ) : null}
        </span>
        <span className="reason-list">
          {event.reasonCodes.slice(0, 3).map((code) => (
            <span key={code} className="reason-chip">
              {code}
            </span>
          ))}
        </span>
      </div>
      {event.riskLevel ? <RiskBadge level={event.riskLevel} /> : null}
      <time className="event-row__time muted-strong" dateTime={event.createdAt}>
        {formatTime(event.createdAt)}
      </time>
    </li>
  )
}

function agentName(agents: { id: string; name: string }[], id: string): string {
  return agents.find((a) => a.id === id)?.name ?? 'unknown agent'
}

export function PageHead({
  title,
  subtitle,
  action,
}: {
  title: string
  subtitle?: string
  action?: React.ReactNode
}) {
  return (
    <div className="page-head">
      <div className="col" style={{ gap: 3 }}>
        <h1 className="page-head__title">{title}</h1>
        {subtitle ? <p className="page-head__sub">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  )
}
