import {
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type FormEvent,
  type SetStateAction,
} from 'react'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ErrorState,
  Field,
  Skeleton,
} from '@/components/ui'
import {
  fixflowApi,
  type FixFlowEquipment,
  type FixFlowRun,
  type KnowledgeDoc,
  type SensorReadings,
} from '@/api/fixflow'
import { PageHead } from './OverviewPage'
import './pages.css'

type Tone = 'neutral' | 'allow' | 'deny' | 'approval' | 'info' | 'warn' | 'critical'

const EMPTY_READINGS: SensorReadings = {
  temperature_c: 0,
  vibration_mm_s: 0,
  pressure_bar: 0,
  flow_m3h: 0,
}

function severityTone(level: string): Tone {
  if (level === 'LOW') return 'allow'
  if (level === 'MEDIUM') return 'approval'
  if (level === 'HIGH') return 'warn'
  if (level === 'CRITICAL') return 'critical'
  return 'neutral'
}

function safetyTone(decision: string): Tone {
  if (decision === 'ALLOW') return 'allow'
  if (decision === 'BLOCK') return 'deny'
  return 'approval'
}

function runTone(status: string): Tone {
  if (status === 'VERIFIED') return 'allow'
  if (status === 'BLOCKED' || status === 'VERIFICATION_FAILED') return 'deny'
  if (status === 'AWAITING_APPROVAL') return 'approval'
  return 'info'
}

function agentTone(status: string): Tone {
  if (status === 'COMPLETED') return 'allow'
  if (status === 'BLOCKED' || status === 'FAILED') return 'deny'
  if (status === 'SIMULATED') return 'warn'
  if (status === 'PENDING') return 'approval'
  return 'neutral'
}

function criticalityTone(value: string): Tone {
  if (value === 'CRITICAL') return 'critical'
  if (value === 'HIGH') return 'warn'
  if (value === 'MEDIUM') return 'approval'
  return 'allow'
}

function readingValue(value: number, digits = 1): string {
  return Number.isFinite(value) ? value.toFixed(digits) : '0.0'
}

export function FixFlowPage() {
  const [equipment, setEquipment] = useState<FixFlowEquipment[]>([])
  const [knowledge, setKnowledge] = useState<KnowledgeDoc[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [readings, setReadings] = useState<SensorReadings>(EMPTY_READINGS)
  const [postReadings, setPostReadings] = useState<SensorReadings>(EMPTY_READINGS)
  const [imageName, setImageName] = useState('')
  const [imageSize, setImageSize] = useState<number | undefined>(undefined)
  const [notes, setNotes] = useState('')
  const [verifyNotes, setVerifyNotes] = useState('Post-maintenance verification run.')
  const [run, setRun] = useState<FixFlowRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selected = useMemo(
    () => equipment.find((item) => item.id === selectedId),
    [equipment, selectedId],
  )

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [items, docs] = await Promise.all([
          fixflowApi.equipment(),
          fixflowApi.knowledge(),
        ])
        if (cancelled) return
        setEquipment(items)
        setKnowledge(docs)
        if (items[0]) {
          setSelectedId(items[0].id)
          setReadings(items[0].sensor_readings)
          setPostReadings(items[0].sensor_readings)
        }
      } catch (caught) {
        if (!cancelled) setError((caught as Error).message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  function selectEquipment(item: FixFlowEquipment) {
    setSelectedId(item.id)
    setReadings(item.sensor_readings)
    setPostReadings(item.sensor_readings)
    setRun(null)
    setError(null)
  }

  function updateReading(
    setter: Dispatch<SetStateAction<SensorReadings>>,
    current: SensorReadings,
    key: keyof SensorReadings,
    value: string,
  ) {
    setter({ ...current, [key]: Number(value) })
  }

  async function startRun(event: FormEvent) {
    event.preventDefault()
    if (!selected) return
    setRunning(true)
    setError(null)
    try {
      const result = await fixflowApi.run({
        equipment_id: selected.id,
        readings,
        image_name: imageName || undefined,
        image_size: imageSize,
        notes: notes || undefined,
      })
      setRun(result)
      setPostReadings(result.readings)
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setRunning(false)
    }
  }

  async function submitVerification(event: FormEvent) {
    event.preventDefault()
    if (!run) return
    setVerifying(true)
    setError(null)
    try {
      const result = await fixflowApi.verify(run.id, postReadings, verifyNotes)
      setRun(result)
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setVerifying(false)
    }
  }

  if (loading) {
    return (
      <div className="col" style={{ gap: 'var(--space-5)' }}>
        <PageHead
          title="FixFlow AI"
          subtitle="Vision-assisted pump maintenance with deterministic safety gating."
        />
        <Skeleton lines={8} height={22} />
      </div>
    )
  }

  if (error && !equipment.length) {
    return (
      <div className="col" style={{ gap: 'var(--space-5)' }}>
        <PageHead title="FixFlow AI" subtitle="Pump maintenance workflow." />
        <ErrorState message={error} onRetry={() => window.location.reload()} />
      </div>
    )
  }

  return (
    <div className="col" style={{ gap: 'var(--space-5)' }}>
      <PageHead
        title="FixFlow AI"
        subtitle="Equipment → inspection → diagnosis → evidence → deterministic safety → plan → verification. Safety rules cannot be overridden by the model."
      />

      {error ? <div className="banner banner--error">{error}</div> : null}

      <Card>
        <CardHeader
          title="1. Select equipment"
          subtitle="Sensor values are pre-filled from the demo asset; adjust them to exercise safety outcomes."
          action={<Badge tone="info">{knowledge.length} knowledge docs loaded</Badge>}
        />
        <div className="grid-2">
          {equipment.map((item) => {
            const active = item.id === selectedId
            return (
              <button
                key={item.id}
                type="button"
                className="card"
                onClick={() => selectEquipment(item)}
                style={{
                  textAlign: 'left',
                  cursor: 'pointer',
                  borderColor: active ? 'var(--accent)' : undefined,
                  boxShadow: active ? '0 0 0 1px var(--accent)' : undefined,
                }}
              >
                <div className="row-between" style={{ alignItems: 'flex-start' }}>
                  <div className="col" style={{ gap: 2 }}>
                    <strong>{item.name}</strong>
                    <span className="muted" style={{ fontSize: 13 }}>
                      {item.manufacturer} {item.model} · {item.location}
                    </span>
                  </div>
                  <Badge tone={criticalityTone(item.criticality)}>{item.criticality}</Badge>
                </div>
                <div className="detail-grid" style={{ marginTop: 'var(--space-3)' }}>
                  <div className="detail">
                    <span className="detail__label">Temperature</span>
                    <span className="detail__value mono">
                      {readingValue(item.sensor_readings.temperature_c)} C
                    </span>
                  </div>
                  <div className="detail">
                    <span className="detail__label">Vibration</span>
                    <span className="detail__value mono">
                      {readingValue(item.sensor_readings.vibration_mm_s)} mm/s
                    </span>
                  </div>
                  <div className="detail">
                    <span className="detail__label">Pressure</span>
                    <span className="detail__value mono">
                      {readingValue(item.sensor_readings.pressure_bar)} bar
                    </span>
                  </div>
                  <div className="detail">
                    <span className="detail__label">Flow</span>
                    <span className="detail__value mono">
                      {readingValue(item.sensor_readings.flow_m3h)} m3/h
                    </span>
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      </Card>

      <Card>
        <CardHeader
          title="2. Capture readings and evidence"
          subtitle="No image pixels are uploaded in this MVP. Image metadata is used only to exercise the simulated vision step."
        />
        <form className="col" style={{ gap: 'var(--space-4)' }} onSubmit={(e) => void startRun(e)}>
          <div className="grid-2">
            <Field label="Temperature (C)" htmlFor="ff-temp">
              <input
                id="ff-temp"
                className="input"
                type="number"
                step="0.1"
                value={readings.temperature_c}
                onChange={(e) =>
                  updateReading(setReadings, readings, 'temperature_c', e.target.value)
                }
              />
            </Field>
            <Field label="Vibration (mm/s RMS)" htmlFor="ff-vibration">
              <input
                id="ff-vibration"
                className="input"
                type="number"
                step="0.1"
                value={readings.vibration_mm_s}
                onChange={(e) =>
                  updateReading(setReadings, readings, 'vibration_mm_s', e.target.value)
                }
              />
            </Field>
            <Field label="Pressure (bar)" htmlFor="ff-pressure">
              <input
                id="ff-pressure"
                className="input"
                type="number"
                step="0.1"
                value={readings.pressure_bar}
                onChange={(e) =>
                  updateReading(setReadings, readings, 'pressure_bar', e.target.value)
                }
              />
            </Field>
            <Field label="Flow (m3/h)" htmlFor="ff-flow">
              <input
                id="ff-flow"
                className="input"
                type="number"
                step="0.1"
                value={readings.flow_m3h}
                onChange={(e) =>
                  updateReading(setReadings, readings, 'flow_m3h', e.target.value)
                }
              />
            </Field>
          </div>

          <div className="grid-2">
            <Field
              label="Inspection image"
              hint="Optional. The vision agent labels its output as simulated and safety ignores it."
              htmlFor="ff-image"
            >
              <input
                id="ff-image"
                className="input"
                type="file"
                accept="image/*"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  setImageName(file?.name ?? '')
                  setImageSize(file?.size)
                }}
              />
            </Field>
            <Field label="Operator notes" htmlFor="ff-notes">
              <input
                id="ff-notes"
                className="input"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Observed noise, leakage, recent work..."
              />
            </Field>
          </div>

          <div className="row-between">
            <span className="muted" style={{ fontSize: 13 }}>
              Selected: {selected?.name ?? 'none'}
            </span>
            <Button type="submit" variant="primary" loading={running} disabled={!selected}>
              Run FixFlow workflow
            </Button>
          </div>
        </form>
      </Card>

      {run ? (
        <>
          <Card>
            <CardHeader
              title="Supervisor summary"
              subtitle={`Run ${run.id.slice(0, 8)} · ${new Date(run.created_at).toLocaleString()}`}
              action={
                <Button variant="ghost" size="sm" onClick={() => setRun(null)}>
                  Clear run
                </Button>
              }
            />
            <div className="detail-grid">
              <div className="detail">
                <span className="detail__label">Workflow status</span>
                <span className="detail__value">
                  <Badge tone={runTone(run.status)}>{run.status}</Badge>
                </span>
              </div>
              <div className="detail">
                <span className="detail__label">Safety decision</span>
                <span className="detail__value">
                  <Badge tone={safetyTone(run.safety.decision)}>{run.safety.decision}</Badge>
                </span>
              </div>
              <div className="detail">
                <span className="detail__label">Diagnosis severity</span>
                <span className="detail__value">
                  <Badge tone={severityTone(run.diagnosis.severity)}>
                    {run.diagnosis.severity}
                  </Badge>
                </span>
              </div>
              <div className="detail">
                <span className="detail__label">Diagnosis source</span>
                <span className="detail__value mono">{run.diagnosis.source}</span>
              </div>
              <div className="detail">
                <span className="detail__label">Downtime estimate</span>
                <span className="detail__value">{run.plan.estimated_downtime_hours} h</span>
              </div>
            </div>
            <div className="table-wrap" style={{ marginTop: 'var(--space-4)' }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Agent</th>
                    <th>Status</th>
                    <th>Output</th>
                    <th>Artifact</th>
                  </tr>
                </thead>
                <tbody>
                  {run.agents.map((agent) => (
                    <tr key={`${agent.role}-${agent.id}`}>
                      <td>
                        <div className="col" style={{ gap: 1 }}>
                          <span className="table__cell-main">{agent.name}</span>
                          <span className="table__cell-sub">{agent.role}</span>
                        </div>
                      </td>
                      <td>
                        <Badge tone={agentTone(agent.status)}>{agent.status}</Badge>
                      </td>
                      <td>{agent.summary}</td>
                      <td className="mono">{agent.artifact_id?.slice(0, 8) ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="grid-2">
            <Card>
              <CardHeader title="Diagnosis" subtitle={run.diagnosis.summary} />
              <ul className="item-list">
                {run.diagnosis.hypotheses.map((item, index) => (
                  <li key={`${item.fault}-${index}`}>
                    <div className="col" style={{ gap: 4, padding: 'var(--space-3) 0' }}>
                      <div className="row-between">
                        <strong>{item.fault}</strong>
                        <Badge tone={item.source === 'ollama' ? 'info' : 'neutral'}>
                          {item.source}
                        </Badge>
                      </div>
                      <span className="muted" style={{ fontSize: 13 }}>
                        Likelihood {Math.round(item.likelihood * 100)}%
                      </span>
                      {item.evidence.map((line) => (
                        <span key={line} className="muted" style={{ fontSize: 13 }}>
                          {line}
                        </span>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
              {run.diagnosis.llm_error ? (
                <p className="muted" style={{ fontSize: 13 }}>
                  Local model unavailable; deterministic fallback used: {run.diagnosis.llm_error}
                </p>
              ) : null}
            </Card>

            <Card>
              <CardHeader
                title="Deterministic safety gate"
                subtitle="Computed from sensor limits only. The model cannot override this decision."
              />
              <div className="col" style={{ gap: 'var(--space-3)' }}>
                <div className="row">
                  <Badge tone={safetyTone(run.safety.decision)}>{run.safety.decision}</Badge>
                  <span className="muted" style={{ fontSize: 13 }}>
                    inspection used: {run.safety.inspection_used ? 'yes' : 'no'}
                  </span>
                </div>
                <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
                  {run.safety.reason_codes.map((code) => (
                    <Badge key={code} tone="neutral">
                      {code}
                    </Badge>
                  ))}
                </div>
                <ul className="item-list">
                  {run.safety.rules.map((rule) => (
                    <li key={rule.rule}>
                      <div className="col" style={{ gap: 2, padding: 'var(--space-3) 0' }}>
                        <div className="row-between">
                          <span className="mono">{rule.rule}</span>
                          <Badge
                            tone={
                              rule.result === 'BLOCK'
                                ? 'deny'
                                : rule.result === 'REQUIRE_APPROVAL'
                                  ? 'approval'
                                  : 'neutral'
                            }
                          >
                            {rule.result}
                          </Badge>
                        </div>
                        <span className="muted" style={{ fontSize: 13 }}>
                          {rule.detail}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </Card>
          </div>

          <Card>
            <CardHeader
              title="Retrieved evidence"
              subtitle="Keyword retrieval over the local maintenance knowledge base."
            />
            <ul className="item-list">
              {run.evidence.map((doc) => (
                <li key={doc.id}>
                  <div className="col" style={{ gap: 4, padding: 'var(--space-3) 0' }}>
                    <div className="row-between">
                      <strong>{doc.title}</strong>
                      <span className="muted mono">score {doc.score}</span>
                    </div>
                    <span className="muted" style={{ fontSize: 12 }}>
                      {doc.source} · {doc.section}
                    </span>
                    <span style={{ fontSize: 13 }}>{doc.content}</span>
                  </div>
                </li>
              ))}
            </ul>
          </Card>

          <Card>
            <CardHeader
              title="Maintenance plan"
              subtitle={run.plan.gate_note}
              action={<Badge tone={safetyTone(run.plan.safety_gate)}>{run.plan.safety_gate}</Badge>}
            />
            <div className="detail-grid" style={{ marginBottom: 'var(--space-4)' }}>
              <div className="detail">
                <span className="detail__label">Estimated downtime</span>
                <span className="detail__value">{run.plan.estimated_downtime_hours} h</span>
              </div>
              <div className="detail">
                <span className="detail__label">Required tools</span>
                <span className="detail__value">{run.plan.required_tools.join(', ')}</span>
              </div>
              <div className="detail">
                <span className="detail__label">Required parts</span>
                <span className="detail__value">
                  {run.plan.required_parts.length ? run.plan.required_parts.join(', ') : 'None'}
                </span>
              </div>
            </div>
            <div className="col" style={{ gap: 'var(--space-3)' }}>
              {run.plan.tasks.map((task) => (
                <div key={task.id} className="card" style={{ padding: 'var(--space-4)' }}>
                  <div className="row-between">
                    <strong>
                      {task.id} · {task.title}
                    </strong>
                    <Badge tone={severityTone(task.priority)}>{task.priority}</Badge>
                  </div>
                  <div className="detail-grid" style={{ marginTop: 'var(--space-3)' }}>
                    <div className="detail">
                      <span className="detail__label">Tools</span>
                      <span className="detail__value">{task.tools.join(', ')}</span>
                    </div>
                    <div className="detail">
                      <span className="detail__label">Parts</span>
                      <span className="detail__value">
                        {task.parts.length ? task.parts.join(', ') : 'None'}
                      </span>
                    </div>
                    <div className="detail">
                      <span className="detail__label">Estimate</span>
                      <span className="detail__value">{task.estimated_hours} h</span>
                    </div>
                  </div>
                  <ol style={{ margin: 'var(--space-3) 0 0', paddingLeft: 20 }}>
                    {task.procedure.map((step) => (
                      <li key={step} style={{ fontSize: 13 }}>
                        {step}
                      </li>
                    ))}
                  </ol>
                  <p className="muted" style={{ fontSize: 12, marginTop: 'var(--space-2)' }}>
                    Acceptance: {task.acceptance.join('; ')}
                  </p>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="3. Verify maintenance"
              subtitle="A failed verification reopens the diagnosis. A passing verification closes the run."
            />
            {run.verification ? (
              <div className="col" style={{ gap: 'var(--space-3)' }}>
                <div className="row">
                  <Badge tone={run.verification.result === 'PASS' ? 'allow' : 'deny'}>
                    {run.verification.result}
                  </Badge>
                  <span className="muted" style={{ fontSize: 13 }}>
                    {run.verification.notes}
                  </span>
                </div>
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Check</th>
                        <th>Value</th>
                        <th>Limit</th>
                        <th>Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {run.verification.checks.map((check) => (
                        <tr key={check.name}>
                          <td>{check.name}</td>
                          <td className="mono">
                            {readingValue(check.value)} {check.unit}
                          </td>
                          <td className="mono">{check.limit}</td>
                          <td>
                            <Badge tone={check.passed ? 'allow' : 'deny'}>
                              {check.passed ? 'PASS' : 'FAIL'}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <form className="col" style={{ gap: 'var(--space-4)' }} onSubmit={(e) => void submitVerification(e)}>
                <div className="grid-2">
                  <Field label="Post temperature (C)" htmlFor="ff-post-temp">
                    <input
                      id="ff-post-temp"
                      className="input"
                      type="number"
                      step="0.1"
                      value={postReadings.temperature_c}
                      onChange={(e) =>
                        updateReading(setPostReadings, postReadings, 'temperature_c', e.target.value)
                      }
                    />
                  </Field>
                  <Field label="Post vibration (mm/s)" htmlFor="ff-post-vibration">
                    <input
                      id="ff-post-vibration"
                      className="input"
                      type="number"
                      step="0.1"
                      value={postReadings.vibration_mm_s}
                      onChange={(e) =>
                        updateReading(setPostReadings, postReadings, 'vibration_mm_s', e.target.value)
                      }
                    />
                  </Field>
                  <Field label="Post pressure (bar)" htmlFor="ff-post-pressure">
                    <input
                      id="ff-post-pressure"
                      className="input"
                      type="number"
                      step="0.1"
                      value={postReadings.pressure_bar}
                      onChange={(e) =>
                        updateReading(setPostReadings, postReadings, 'pressure_bar', e.target.value)
                      }
                    />
                  </Field>
                  <Field label="Post flow (m3/h)" htmlFor="ff-post-flow">
                    <input
                      id="ff-post-flow"
                      className="input"
                      type="number"
                      step="0.1"
                      value={postReadings.flow_m3h}
                      onChange={(e) =>
                        updateReading(setPostReadings, postReadings, 'flow_m3h', e.target.value)
                      }
                    />
                  </Field>
                </div>
                <Field label="Verification notes" htmlFor="ff-verify-notes">
                  <input
                    id="ff-verify-notes"
                    className="input"
                    value={verifyNotes}
                    onChange={(e) => setVerifyNotes(e.target.value)}
                  />
                </Field>
                <div className="row" style={{ justifyContent: 'flex-end' }}>
                  <Button type="submit" variant="primary" loading={verifying}>
                    Submit verification
                  </Button>
                </div>
              </form>
            )}
          </Card>

          {run.diagnosis_reopened && run.reopened_diagnosis ? (
            <Card>
              <CardHeader
                title="Diagnosis reopened"
                subtitle="Verification failed, so FixFlow reopened the deterministic diagnosis."
                action={
                  <Badge tone={severityTone(run.reopened_diagnosis.severity)}>
                    {run.reopened_diagnosis.severity}
                  </Badge>
                }
              />
              <p>{run.reopened_diagnosis.summary}</p>
              <ul className="item-list">
                {run.reopened_diagnosis.hypotheses.map((item, index) => (
                  <li key={`${item.fault}-${index}`}>
                    <div className="row-between" style={{ padding: 'var(--space-3) 0' }}>
                      <span>{item.fault}</span>
                      <span className="mono">{Math.round(item.likelihood * 100)}%</span>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
