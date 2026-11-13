import { useState } from 'react'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Skeleton } from '@/components/ui'
import { v2Api, type BenchmarkDto } from '@/api/client'
import { PageHead } from './OverviewPage'
import { useAsync } from './useAsync'
import './pages.css'

function metric(value: unknown): string {
  if (value === null || value === undefined) return 'n/a'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(4)
  return String(value)
}

export function BenchmarksPage() {
  const [result, setResult] = useState<BenchmarkDto | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const audit = useAsync(() => v2Api.auditVerify())

  async function run() {
    setRunning(true)
    setError(null)
    try {
      setResult(await v2Api.runBenchmark())
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="col" style={{ gap: 'var(--space-5)' }}>
      <PageHead
        title="Failure propagation benchmark"
        subtitle="AFPB measures whether deterministic provenance checks stop unsafe actions that the same policy engine would otherwise allow. Every number comes from a real run of the service."
        action={
          <Button variant="primary" loading={running} onClick={() => void run()}>
            Run AFPB
          </Button>
        }
      />

      {error ? <div className="banner banner--error">{error}</div> : null}

      {running ? <Skeleton lines={5} height={20} /> : null}

      {!result && !running ? (
        <Card>
          <EmptyState
            title="No benchmark run in this view"
            description="Run AFPB to execute the isolated scenario suite. The baseline is an explicit policy-only ablation, not historical production traffic."
            action={
              <Button variant="primary" loading={running} onClick={() => void run()}>
                Run benchmark
              </Button>
            }
          />
        </Card>
      ) : null}

      {result ? (
        <>
          <Card>
            <CardHeader
              title={`Run ${result.run_id ?? ''}`}
              subtitle={`Suite ${result.suite} · seed ${result.seed} · ${result.scenarios.length} scenarios`}
            />
            <div className="detail-grid">
              {Object.entries(result.aggregate)
                .filter(([key]) => key !== 'methodology')
                .map(([key, value]) => (
                  <div className="detail" key={key}>
                    <span className="detail__label">{key.replaceAll('_', ' ')}</span>
                    <span className="detail__value mono">{metric(value)}</span>
                  </div>
                ))}
            </div>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 'var(--space-3)' }}>
              {result.methodology}
            </p>
          </Card>

          <Card className="page-card">
            <CardHeader title="Scenario results" subtitle="Baseline vs full V2 decision service." />
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Scenario</th>
                    <th>Baseline</th>
                    <th>AgentGuard V2</th>
                    <th>Propagation</th>
                    <th>Expected</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {result.scenarios.map((scenario) => (
                    <tr key={scenario.scenario}>
                      <td>
                        <div className="col" style={{ gap: 1 }}>
                          <span className="table__cell-main">{scenario.scenario.replaceAll('_', ' ')}</span>
                          <span className="table__cell-sub">{scenario.description}</span>
                        </div>
                      </td>
                      <td>
                        <Badge tone={scenario.baseline.decision === 'ALLOW' ? 'warn' : 'neutral'}>
                          {String(scenario.baseline.decision)}
                        </Badge>
                      </td>
                      <td>
                        <Badge
                          tone={
                            scenario.agentguard_v2.decision === 'DENY'
                              ? 'deny'
                              : scenario.agentguard_v2.decision === 'REQUIRE_APPROVAL'
                                ? 'approval'
                                : 'allow'
                          }
                        >
                          {String(scenario.agentguard_v2.decision)}
                        </Badge>
                      </td>
                      <td className="mono" style={{ fontSize: 12 }}>
                        {String(scenario.agentguard_v2.propagation_effect ?? 'NONE')}
                      </td>
                      <td>
                        <Badge tone="neutral">{scenario.expected_effect}</Badge>
                      </td>
                      <td>
                        <Badge tone={scenario.passed ? 'allow' : 'critical'}>
                          {scenario.passed ? 'PASS' : 'FAIL'}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      ) : null}

      <Card>
        <CardHeader
          title="Audit chain"
          subtitle="Hash-chain verification is internal consistency evidence, not proof against a privileged database attacker. Anchor checkpoints externally."
          action={
            <Button variant="ghost" size="sm" onClick={() => void audit.reload()}>
              Verify now
            </Button>
          }
        />
        {audit.loading ? (
          <Skeleton lines={2} />
        ) : audit.error ? (
          <ErrorState message={audit.error} onRetry={() => void audit.reload()} />
        ) : audit.data ? (
          <div className="detail-grid">
            <div className="detail">
              <span className="detail__label">Chain</span>
              <span className="detail__value">
                <Badge tone={audit.data.valid ? 'allow' : 'critical'}>
                  {audit.data.valid ? 'VALID' : 'BROKEN'}
                </Badge>
              </span>
            </div>
            <div className="detail">
              <span className="detail__label">Events checked</span>
              <span className="detail__value mono">{metric(audit.data.checked)}</span>
            </div>
            <div className="detail">
              <span className="detail__label">Legacy unchained events</span>
              <span className="detail__value mono">{metric(audit.data.unchained_legacy_events)}</span>
            </div>
          </div>
        ) : null}
      </Card>
    </div>
  )
}
