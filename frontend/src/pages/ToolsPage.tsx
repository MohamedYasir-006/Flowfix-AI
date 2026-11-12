import { useData } from '@/api/DataContext'
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  RiskBadge,
  Skeleton,
} from '@/components/ui'
import { PageHead } from './OverviewPage'
import { formatTime } from './format'
import './pages.css'

const CATEGORY_TONE: Record<string, 'neutral' | 'info' | 'approval' | 'warn' | 'critical'> = {
  read: 'info',
  write: 'approval',
  external: 'warn',
  destructive: 'critical',
}

export function ToolsPage() {
  const { tools, agents, loading, error, refresh } = useData()

  return (
    <div className="col" style={{ gap: 'var(--space-5)' }}>
      <PageHead
        title="Tools"
        subtitle="Registry of tools an agent can call, their risk category, and the input schema each call must satisfy."
      />

      {loading ? (
        <Skeleton lines={6} height={20} />
      ) : error ? (
        <ErrorState message={error} onRetry={() => void refresh()} />
      ) : tools.length === 0 ? (
        <Card>
          <EmptyState
            title="No tools registered"
            description="Tools must be registered before an agent can be granted permission to call them."
          />
        </Card>
      ) : (
        <div className="tool-grid">
          {tools.map((tool) => {
            const usedBy = agents.filter((a) => a.toolIds.includes(tool.id))
            return (
              <Card key={tool.id} className="tool-card">
                <div className="row-between">
                  <span className="mono tool-card__name">{tool.name}</span>
                  <Badge tone={tool.status === 'ACTIVE' ? 'allow' : 'neutral'}>{tool.status}</Badge>
                </div>

                <p className="muted tool-card__desc">{tool.description}</p>

                <div className="row" style={{ gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                  <Badge tone={CATEGORY_TONE[tool.category] ?? 'neutral'}>{tool.category}</Badge>
                  <RiskBadge level={tool.defaultRisk} />
                </div>

                <div className="col" style={{ gap: 5 }}>
                  <span className="field__label">Input schema</span>
                  <div className="code-block">{JSON.stringify(tool.inputSchema, null, 2)}</div>
                </div>

                <div className="tool-card__footer">
                  <span className="muted-strong" style={{ fontSize: 12 }}>
                    Used by {usedBy.length} agent{usedBy.length === 1 ? '' : 's'}
                    {usedBy.length ? ` · ${usedBy.map((a) => a.name).join(', ')}` : ''}
                  </span>
                  <span className="muted-strong" style={{ fontSize: 12 }}>
                    Added {formatTime(tool.createdAt)}
                  </span>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
