import { useState } from 'react'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Field, Skeleton } from '@/components/ui'
import {
  v2Api,
  type GraphDto,
  type TimelineEntryDto,
  type WorkflowExecutionDto,
} from '@/api/client'
import { PageHead } from './OverviewPage'
import { formatTime } from './format'
import { useAsync } from './useAsync'
import './pages.css'

export function ProvenancePage() {
  const executions = useAsync(() => v2Api.executions())
  const artifacts = useAsync(() => v2Api.artifacts())
  const [graph, setGraph] = useState<GraphDto | null>(null)
  const [timeline, setTimeline] = useState<TimelineEntryDto[] | null>(null)
  const [inspectError, setInspectError] = useState<string | null>(null)
  const [inspecting, setInspecting] = useState<string | null>(null)

  const [lineageId, setLineageId] = useState('')
  const [lineage, setLineage] = useState<Record<string, unknown> | null>(null)
  const [lineageError, setLineageError] = useState<string | null>(null)

  async function inspect(execution: WorkflowExecutionDto) {
    setInspecting(execution.id)
    setInspectError(null)
    try {
      const [graphValue, timelineValue] = await Promise.all([
        v2Api.graph(execution.id),
        v2Api.timeline(execution.id),
      ])
      setGraph(graphValue)
      setTimeline(timelineValue)
    } catch (caught) {
      setInspectError((caught as Error).message)
    } finally {
      setInspecting(null)
    }
  }

  async function loadLineage() {
    setLineageError(null)
    setLineage(null)
    try {
      setLineage(await v2Api.lineage(lineageId.trim()))
    } catch (caught) {
      setLineageError((caught as Error).message)
    }
  }

  return (
    <div className="col" style={{ gap: 'var(--space-5)' }}>
      <PageHead
        title="Provenance and workflows"
        subtitle="Workflow-scoped artifacts, dependency edges, and the chronological evidence used by the propagation engine. Lineage is bounded and tenant-scoped."
      />

      {executions.loading ? (
        <Skeleton lines={5} height={20} />
      ) : executions.error ? (
        <ErrorState message={executions.error} onRetry={() => void executions.reload()} />
      ) : !executions.data?.length ? (
        <Card>
          <EmptyState
            title="No workflow executions"
            description="Start a workflow execution to attach artifacts and evaluate actions against upstream provenance."
          />
        </Card>
      ) : (
        <Card className="page-card">
          <CardHeader title="Workflow executions" subtitle={`${executions.data.length} execution(s)`} />
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Execution</th>
                  <th>Workflow</th>
                  <th>External key</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {executions.data.map((execution) => (
                  <tr key={execution.id}>
                    <td className="mono">{execution.id}</td>
                    <td className="mono muted">{execution.workflow_id}</td>
                    <td>{execution.external_key ?? '—'}</td>
                    <td>
                      <Badge tone={execution.status === 'RUNNING' ? 'info' : execution.status === 'PAUSED' ? 'approval' : 'neutral'}>
                        {execution.status}
                      </Badge>
                    </td>
                    <td className="muted">{formatTime(execution.started_at)}</td>
                    <td>
                      <Button
                        variant="ghost"
                        size="sm"
                        loading={inspecting === execution.id}
                        onClick={() => void inspect(execution)}
                      >
                        Inspect
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {inspectError ? <div className="banner banner--error">{inspectError}</div> : null}

      {graph && timeline ? (
        <div className="grid-2">
          <Card>
            <CardHeader
              title="Dependency graph"
              subtitle={`${graph.nodes.length} nodes · ${graph.edges.length} edges · ${graph.cycles.length} cycle(s)`}
            />
            {graph.cycles.length ? (
              <div className="banner banner--error">
                Cycle detected: {graph.cycles.map((cycle) => cycle.join(' → ')).join('; ')}
              </div>
            ) : null}
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Edge</th>
                    <th>Relationship</th>
                    <th>Validation</th>
                  </tr>
                </thead>
                <tbody>
                  {graph.edges.map((edge) => (
                    <tr key={edge.id}>
                      <td className="mono" style={{ fontSize: 12 }}>
                        {edge.source} → {edge.target}
                      </td>
                      <td>{edge.relationship}</td>
                      <td>
                        <Badge tone={edge.validation_status === 'VALIDATED' ? 'allow' : edge.validation_status === 'INVALID' ? 'critical' : 'approval'}>
                          {edge.validation_status}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card>
            <CardHeader title="Recorded timeline" subtitle="Chronological evidence; replay does not re-run tools." />
            <ul className="event-list event-list--divided">
              {timeline.map((entry, index) => (
                <li key={`${entry.timestamp}-${index}`}>
                  <div className="event-row">
                    <div className="grow col" style={{ gap: 1 }}>
                      <span className="item-row__title">{entry.summary}</span>
                      <span className="item-row__sub">{entry.kind}</span>
                    </div>
                    <span className="event-row__time muted">{formatTime(entry.timestamp)}</span>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      ) : null}

      <div className="grid-2">
        <Card>
          <CardHeader title="Artifacts" subtitle={`${artifacts.data?.length ?? 0} recorded artifact(s)`} />
          {artifacts.loading ? (
            <Skeleton lines={3} />
          ) : artifacts.error ? (
            <ErrorState message={artifacts.error} onRetry={() => void artifacts.reload()} />
          ) : !artifacts.data?.length ? (
            <p className="muted">No artifacts recorded.</p>
          ) : (
            <ul className="item-list">
              {artifacts.data.slice(0, 10).map((artifact) => (
                <li key={String(artifact.id)}>
                  <div className="item-row">
                    <div className="grow col" style={{ gap: 1 }}>
                      <span className="item-row__title">
                        {String(artifact.name || artifact.artifact_type)}
                      </span>
                      <span className="item-row__sub mono">{String(artifact.id)}</span>
                    </div>
                    <Badge
                      tone={
                        artifact.validation_status === 'VALIDATED'
                          ? 'allow'
                          : artifact.validation_status === 'INVALID'
                            ? 'critical'
                            : 'approval'
                      }
                    >
                      {String(artifact.validation_status)}
                    </Badge>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <CardHeader title="Artifact lineage" subtitle="Walk parent artifacts and depends_on edges." />
          <div className="row" style={{ gap: 'var(--space-2)', alignItems: 'flex-end' }}>
            <div className="grow">
              <Field label="Artifact ID" htmlFor="lineage-id">
                <input
                  id="lineage-id"
                  className="input mono"
                  value={lineageId}
                  onChange={(event) => setLineageId(event.target.value)}
                  placeholder="artifact id"
                />
              </Field>
            </div>
            <Button variant="primary" disabled={!lineageId.trim()} onClick={() => void loadLineage()}>
              Trace
            </Button>
          </div>
          {lineageError ? <div className="banner banner--error">{lineageError}</div> : null}
          {lineage ? (
            <ul className="item-list" style={{ marginTop: 'var(--space-3)' }}>
              {(lineage.nodes as Array<Record<string, unknown>>).map((node) => (
                <li key={String(node.id)}>
                  <div className="item-row">
                    <div className="grow col" style={{ gap: 1 }}>
                      <span className="item-row__title">
                        {String(node.name || node.artifact_type)} · depth {String(node.depth)}
                      </span>
                      <span className="item-row__sub mono">{String(node.id)}</span>
                    </div>
                    <Badge tone={node.validation_status === 'VALIDATED' ? 'allow' : 'approval'}>
                      {String(node.validation_status)}
                    </Badge>
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </Card>
      </div>
    </div>
  )
}
