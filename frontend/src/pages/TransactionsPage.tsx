import { useState } from 'react'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Skeleton } from '@/components/ui'
import { v2Api, type TransactionDto } from '@/api/client'
import { PageHead } from './OverviewPage'
import { formatTime } from './format'
import { useAsync } from './useAsync'
import './pages.css'

function statusTone(status: string): 'allow' | 'approval' | 'warn' | 'critical' | 'neutral' | 'info' {
  if (status === 'COMPLETED') return 'allow'
  if (status === 'RUNNING' || status === 'CREATED') return 'info'
  if (status === 'WAITING_APPROVAL' || status === 'COMPENSATING') return 'approval'
  if (status === 'RECOVERY_REQUIRED') return 'warn'
  if (status === 'FAILED') return 'critical'
  return 'neutral'
}

export function TransactionsPage() {
  const transactions = useAsync(() => v2Api.transactions())
  const [plan, setPlan] = useState<Record<string, unknown> | null>(null)
  const [planFor, setPlanFor] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function showPlan(transaction: TransactionDto) {
    setPlanFor(transaction.id)
    setError(null)
    try {
      setPlan(await v2Api.recoveryPlan(transaction.id))
    } catch (caught) {
      setError((caught as Error).message)
    }
  }

  return (
    <div className="col" style={{ gap: 'var(--space-5)' }}>
      <PageHead
        title="Transaction integrity"
        subtitle="Saga-style step tracking with idempotency keys, retry budgets, partial-failure detection, and explicitly approved compensation. Compensation is a new external action, not a guaranteed rollback."
      />

      {error ? <div className="banner banner--error">{error}</div> : null}

      {transactions.loading ? (
        <Skeleton lines={5} height={20} />
      ) : transactions.error ? (
        <ErrorState message={transactions.error} onRetry={() => void transactions.reload()} />
      ) : !transactions.data?.length ? (
        <Card>
          <EmptyState
            title="No transactions"
            description="Agents create transactions through POST /api/v1/transactions before performing multi-step external work."
          />
        </Card>
      ) : (
        <Card className="page-card">
          <CardHeader title="Transactions" subtitle={`${transactions.data.length} recorded transaction(s)`} />
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Transaction</th>
                  <th>Status</th>
                  <th>Idempotency key</th>
                  <th>Steps</th>
                  <th>Updated</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {transactions.data.map((transaction) => (
                  <tr key={transaction.id}>
                    <td className="mono">{transaction.id}</td>
                    <td>
                      <Badge tone={statusTone(transaction.status)}>{transaction.status}</Badge>
                    </td>
                    <td className="mono muted">{transaction.idempotency_key ?? '—'}</td>
                    <td>
                      <div className="row" style={{ gap: 4, flexWrap: 'wrap' }}>
                        {transaction.steps.map((step) => (
                          <Badge
                            key={step.id}
                            tone={
                              step.status === 'COMPLETED'
                                ? 'allow'
                                : step.status === 'FAILED'
                                  ? 'critical'
                                  : 'neutral'
                            }
                          >
                            {step.step_key}: {step.status}
                          </Badge>
                        ))}
                      </div>
                    </td>
                    <td className="muted">{formatTime(transaction.updated_at)}</td>
                    <td>
                      <Button variant="ghost" size="sm" onClick={() => void showPlan(transaction)}>
                        Recovery plan
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {plan ? (
        <Card>
          <CardHeader
            title="Recovery plan"
            subtitle={`Transaction ${String(planFor ?? plan.transaction_id)}`}
          />
          <div className="detail-grid">
            <div className="detail">
              <span className="detail__label">Status</span>
              <span className="detail__value">{String(plan.status)}</span>
            </div>
            <div className="detail">
              <span className="detail__label">Failed steps</span>
              <span className="detail__value mono">
                {(plan.failed_steps as string[]).join(', ') || 'none'}
              </span>
            </div>
            <div className="detail">
              <span className="detail__label">Completed steps</span>
              <span className="detail__value mono">
                {(plan.completed_steps as string[]).join(', ') || 'none'}
              </span>
            </div>
            <div className="detail">
              <span className="detail__label">Compensation requires approval</span>
              <span className="detail__value">{plan.requires_approval ? 'yes' : 'no'}</span>
            </div>
          </div>
          <p className="muted">{String(plan.note)}</p>
        </Card>
      ) : null}
    </div>
  )
}
