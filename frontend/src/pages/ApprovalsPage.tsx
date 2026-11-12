import { useState } from 'react'
import { useData } from '@/api/DataContext'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  RiskBadge,
  Skeleton,
} from '@/components/ui'
import { PageHead } from './OverviewPage'
import { formatTime } from './format'
import type { Approval } from '@/types'
import './pages.css'

const TABS = ['PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'CONSUMED'] as const

export function ApprovalsPage() {
  const { approvals, loading, error, refresh, decideApproval, agents, users } = useData()
  const [tab, setTab] = useState<(typeof TABS)[number]>('PENDING')
  const [busy, setBusy] = useState<string | null>(null)
  const [selected, setSelected] = useState<Approval | null>(null)

  const counts = approvals.reduce<Record<string, number>>((acc, a) => {
    acc[a.status] = (acc[a.status] ?? 0) + 1
    return acc
  }, {})

  const list = approvals
    .filter((a) => a.status === tab)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))

  async function decide(approval: Approval, decision: 'APPROVED' | 'REJECTED') {
    setBusy(approval.id)
    try {
      await decideApproval(approval.id, decision)
      setSelected(null)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="col" style={{ gap: 'var(--space-5)' }}>
      <PageHead
        title="Approvals"
        subtitle="Protected actions that need a human decision. Approval is bound to the exact payload and re-checked against current policy before anything executes."
      />

      <div className="tabs" role="tablist" aria-label="Approval status">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={`tab ${tab === t ? 'tab--active' : ''}`}
            onClick={() => setTab(t)}
          >
            {labelFor(t)}
            {counts[t] ? <span className="tab__count">{counts[t]}</span> : null}
          </button>
        ))}
      </div>

      {loading ? (
        <Skeleton lines={5} height={20} />
      ) : error ? (
        <ErrorState message={error} onRetry={() => void refresh()} />
      ) : list.length === 0 ? (
        <Card>
          <EmptyState
            title={`No ${labelFor(tab).toLowerCase()} approvals`}
            description={
              tab === 'PENDING'
                ? 'When an agent proposes a protected action, it will wait here until an approver decides.'
                : 'Approvals in this state will appear here.'
            }
          />
        </Card>
      ) : (
        <Card>
          <ul className="item-list">
            {list.map((a) => (
              <li key={a.id}>
                <button
                  className="item-row item-row--button"
                  onClick={() => setSelected(a)}
                  aria-label={`Review approval for ${a.toolName} to ${a.target}`}
                >
                  <div className="grow col" style={{ gap: 3 }}>
                    <span className="item-row__title mono">{a.toolName}</span>
                    <span className="item-row__sub">
                      {agentName(agents, a.requestedByAgentId)} → {a.target} ·{' '}
                      {formatTime(a.createdAt)}
                    </span>
                    {a.approverUserId ? (
                      <span className="item-row__sub">
                        Decided by {userName(users, a.approverUserId)}
                        {a.decidedAt ? ` · ${formatTime(a.decidedAt)}` : ''}
                      </span>
                    ) : (
                      <span className="item-row__sub">Expires {formatTime(a.expiresAt)}</span>
                    )}
                  </div>
                  <RiskBadge level={a.riskLevel} />
                  <Badge tone={toneFor(a.status)}>{a.status}</Badge>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {selected ? (
        <ApprovalDetail
          approval={selected}
          agents={agents}
          users={users}
          busy={busy === selected.id}
          onDecide={decide}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  )
}

function ApprovalDetail({
  approval,
  agents,
  users,
  busy,
  onDecide,
  onClose,
}: {
  approval: Approval
  agents: { id: string; name: string }[]
  users: { id: string; displayName: string; role: string }[]
  busy: boolean
  onDecide: (a: Approval, d: 'APPROVED' | 'REJECTED') => void
  onClose: () => void
}) {
  const [reason, setReason] = useState('')
  const canDecide = approval.status === 'PENDING' && !busy

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__head">
          <div className="col" style={{ gap: 2 }}>
            <h2 id="approval-title">Review approval</h2>
            <p className="muted" style={{ fontSize: 12.5 }}>
              Action {approval.actionId} · policy v{approval.policyVersion}
            </p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="modal__body col" style={{ gap: 'var(--space-4)' }}>
          <div className="detail-grid">
            <Detail label="Requested by" value={agentName(agents, approval.requestedByAgentId)} />
            <Detail label="Tool" value={<span className="mono">{approval.toolName}</span>} />
            <Detail label="Target" value={approval.target} />
            <Detail label="Risk" value={<RiskBadge level={approval.riskLevel} />} />
            <Detail label="Status" value={<Badge tone={toneFor(approval.status)}>{approval.status}</Badge>} />
            <Detail label="Expires" value={formatTime(approval.expiresAt)} />
            {approval.approverUserId ? (
              <Detail
                label="Decided by"
                value={`${userName(users, approval.approverUserId)} (${userRole(users, approval.approverUserId)})`}
              />
            ) : null}
          </div>

          <div className="col" style={{ gap: 5 }}>
            <span className="field__label">Reason for review</span>
            <div className="reason-list">
              <span className="reason-chip">{approval.reason}</span>
            </div>
          </div>

          <div className="col" style={{ gap: 5 }}>
            <span className="field__label">Sanitized arguments</span>
            <div className="code-block">{JSON.stringify(approval.argumentsSummary, null, 2)}</div>
            <p className="field__hint">
              Sensitive fields are redacted before storage. The full payload is never shown in the UI.
            </p>
          </div>

          <div className="col" style={{ gap: 5 }}>
            <span className="field__label">Payload hash</span>
            <div className="code-block">{approval.payloadHash}</div>
            <p className="field__hint">
              The approval is bound to this exact payload. If anything changes, the approval becomes invalid.
            </p>
          </div>

          {canDecide ? (
            <div className="col" style={{ gap: 'var(--space-3)' }}>
              <textarea
                className="textarea"
                placeholder="Optional note explaining your decision (visible in the audit trail)…"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                aria-label="Decision note"
              />
              <div className="row" style={{ gap: 'var(--space-2)' }}>
                <Button
                  variant="success"
                  disabled={busy}
                  loading={busy}
                  onClick={() => onDecide(approval, 'APPROVED')}
                >
                  Approve and allow execution
                </Button>
                <Button
                  variant="danger"
                  disabled={busy}
                  loading={busy}
                  onClick={() => onDecide(approval, 'REJECTED')}
                >
                  Reject
                </Button>
              </div>
              <p className="field__hint">
                Approving does not execute the action immediately. Policy is re-evaluated first, and the action
                runs at most once.
              </p>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="detail">
      <span className="detail__label">{label}</span>
      <span className="detail__value">{value}</span>
    </div>
  )
}

function labelFor(status: string): string {
  switch (status) {
    case 'PENDING':
      return 'Pending'
    case 'APPROVED':
      return 'Approved'
    case 'REJECTED':
      return 'Rejected'
    case 'EXPIRED':
      return 'Expired'
    case 'CONSUMED':
      return 'Consumed'
    default:
      return status
  }
}

function toneFor(status: string): 'allow' | 'deny' | 'approval' | 'neutral' {
  switch (status) {
    case 'APPROVED':
    case 'CONSUMED':
      return 'allow'
    case 'REJECTED':
      return 'deny'
    case 'PENDING':
      return 'approval'
    default:
      return 'neutral'
  }
}

function agentName(agents: { id: string; name: string }[], id: string): string {
  return agents.find((a) => a.id === id)?.name ?? 'unknown agent'
}

function userName(users: { id: string; displayName: string }[], id: string): string {
  return users.find((u) => u.id === id)?.displayName ?? 'unknown'
}

function userRole(users: { id: string; role: string }[], id: string): string {
  return users.find((u) => u.id === id)?.role ?? '—'
}
