import { useMemo, useState } from 'react'
import { useData } from '@/api/DataContext'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Skeleton,
} from '@/components/ui'
import { PageHead, EventRow } from './OverviewPage'
import type { Decision, EventType } from '@/types'
import './pages.css'

export function ActivityPage() {
  const { events, loading, error, refresh, eventFilters, setEventFilters, agents, tools } = useData()
  const [page, setPage] = useState(1)
  const pageSize = 20

  const filtered = events

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize))
  const currentPage = Math.min(page, pageCount)
  const pageItems = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize)

  const hasFilters = Boolean(
    (eventFilters.decision && eventFilters.decision !== 'ALL') ||
      (eventFilters.eventType && eventFilters.eventType !== 'ALL') ||
      eventFilters.agentId ||
      eventFilters.toolName ||
      eventFilters.search,
  )

  const decisionCounts = useMemo(() => {
    const counts: Record<string, number> = { ALLOW: 0, DENY: 0, REQUIRE_APPROVAL: 0 }
    for (const e of events) {
      if (e.decision && counts[e.decision] !== undefined) counts[e.decision] += 1
    }
    return counts
  }, [events])

  return (
    <div className="col" style={{ gap: 'var(--space-5)' }}>
      <PageHead
        title="Activity"
        subtitle="Every policy decision, approval, execution, and administrative change — searchable and exportable."
      />

      <Card>
        <div className="filters">
          <div className="filters__search">
            <input
              className="input"
              type="search"
              placeholder="Search by agent, tool, action ID, or reason code…"
              value={eventFilters.search ?? ''}
              onChange={(e) => {
                setEventFilters({ ...eventFilters, search: e.target.value })
                setPage(1)
              }}
              aria-label="Search activity"
            />
          </div>

          <div className="filters__group">
            <select
              className="select"
              value={eventFilters.decision ?? 'ALL'}
              onChange={(e) => {
                setEventFilters({ ...eventFilters, decision: e.target.value as Decision | 'ALL' })
                setPage(1)
              }}
              aria-label="Filter by decision"
            >
              <option value="ALL">All decisions ({decisionCounts.ALLOW + decisionCounts.DENY + decisionCounts.REQUIRE_APPROVAL})</option>
              <option value="ALLOW">Allowed ({decisionCounts.ALLOW})</option>
              <option value="DENY">Blocked ({decisionCounts.DENY})</option>
              <option value="REQUIRE_APPROVAL">Needs approval ({decisionCounts.REQUIRE_APPROVAL})</option>
            </select>

            <select
              className="select"
              value={eventFilters.eventType ?? 'ALL'}
              onChange={(e) => {
                setEventFilters({ ...eventFilters, eventType: e.target.value as EventType | 'ALL' })
                setPage(1)
              }}
              aria-label="Filter by event type"
            >
              <option value="ALL">All event types</option>
              <option value="decision">Decisions</option>
              <option value="approval">Approvals</option>
              <option value="execution">Executions</option>
              <option value="admin">Administrative</option>
            </select>

            <select
              className="select"
              value={eventFilters.agentId ?? ''}
              onChange={(e) => {
                setEventFilters({ ...eventFilters, agentId: e.target.value || undefined })
                setPage(1)
              }}
              aria-label="Filter by agent"
            >
              <option value="">All agents</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>

            <select
              className="select"
              value={eventFilters.toolName ?? ''}
              onChange={(e) => {
                setEventFilters({ ...eventFilters, toolName: e.target.value || undefined })
                setPage(1)
              }}
              aria-label="Filter by tool"
            >
              <option value="">All tools</option>
              {tools.map((t) => (
                <option key={t.id} value={t.name}>
                  {t.name}
                </option>
              ))}
            </select>

            {hasFilters ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setEventFilters({ decision: 'ALL', eventType: 'ALL' })
                  setPage(1)
                }}
              >
                Clear filters
              </Button>
            ) : null}
          </div>
        </div>
      </Card>

      {loading ? (
        <Skeleton lines={8} height={18} />
      ) : error ? (
        <ErrorState message={error} onRetry={() => void refresh()} />
      ) : pageItems.length === 0 ? (
        <Card>
          <EmptyState
            title={hasFilters ? 'No events match these filters' : 'No activity recorded yet'}
            description={
              hasFilters
                ? 'Try widening the decision, agent, or tool filters.'
                : 'As soon as an agent calls a tool through AgentGuard, its decision will be recorded here.'
            }
          />
        </Card>
      ) : (
        <Card>
          <ul className="event-list event-list--divided">
            {pageItems.map((e) => (
              <EventRow key={e.id} event={e} />
            ))}
          </ul>
          <div className="pager">
            <span className="muted" style={{ fontSize: 12.5 }}>
              Showing {(currentPage - 1) * pageSize + 1}–
              {Math.min(currentPage * pageSize, filtered.length)} of {filtered.length} events
            </span>
            <div className="row" style={{ gap: 'var(--space-2)' }}>
              <Button
                variant="secondary"
                size="sm"
                disabled={currentPage <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={currentPage >= pageCount}
                onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
              >
                Next
              </Button>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
