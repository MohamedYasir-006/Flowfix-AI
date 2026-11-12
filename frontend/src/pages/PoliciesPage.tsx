import { useState } from 'react'
import { useData } from '@/api/DataContext'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Skeleton,
} from '@/components/ui'
import { Modal } from '@/components/Modal'
import { PageHead } from './OverviewPage'
import { formatTime } from './format'
import type { Policy, PolicyEffect, PolicyRule } from '@/types'
import './pages.css'

const EFFECT_TONE: Record<PolicyEffect, 'allow' | 'deny' | 'approval'> = {
  ALLOW: 'allow',
  DENY: 'deny',
  REQUIRE_APPROVAL: 'approval',
}

const EFFECTS: PolicyEffect[] = ['ALLOW', 'DENY', 'REQUIRE_APPROVAL']
const RISK_LEVELS = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as const
const CATEGORIES = ['read', 'write', 'external', 'destructive'] as const

export function PoliciesPage() {
  const { policies, loading, error, refresh, publishPolicy, createPolicy } = useData()
  const [busy, setBusy] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Policy | null>(null)
  const [editing, setEditing] = useState<Policy | 'new' | null>(null)

  async function publish(policy: Policy) {
    setBusy(policy.id)
    try {
      await publishPolicy(policy.id)
      setExpanded(null)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="col" style={{ gap: 'var(--space-5)' }}>
      <PageHead
        title="Policies"
        subtitle="Deterministic rules evaluated before any tool runs. Precedence: disabled agent → unregistered tool → missing permission → explicit deny → approval rule → allow rule → default deny."
        action={
          <Button variant="primary" onClick={() => setEditing('new')}>
            New policy
          </Button>
        }
      />

      {loading ? (
        <Skeleton lines={5} height={20} />
      ) : error ? (
        <ErrorState message={error} onRetry={() => void refresh()} />
      ) : policies.length === 0 ? (
        <Card>
          <EmptyState
            title="No policies defined"
            description="Without an active policy every action falls through to default deny."
            action={
              <Button variant="primary" onClick={() => setEditing('new')}>
                Create the first policy
              </Button>
            }
          />
        </Card>
      ) : (
        <Card className="page-card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Policy</th>
                  <th>Version</th>
                  <th>Default effect</th>
                  <th>Rules</th>
                  <th>Status</th>
                  <th>Updated</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {policies.map((policy) => (
                  <tr key={policy.id}>
                    <td>
                      <div className="col" style={{ gap: 2 }}>
                        <span className="table__cell-main">{policy.name}</span>
                        <span className="table__cell-sub" style={{ maxWidth: 340 }}>
                          {policy.description}
                        </span>
                      </div>
                    </td>
                    <td className="mono">v{policy.version}</td>
                    <td>
                      <Badge tone={EFFECT_TONE[policy.defaultEffect]}>{policy.defaultEffect}</Badge>
                    </td>
                    <td>{policy.rules.length}</td>
                    <td>
                      <Badge
                        tone={
                          policy.status === 'ACTIVE'
                            ? 'allow'
                            : policy.status === 'DRAFT'
                              ? 'approval'
                              : 'neutral'
                        }
                      >
                        {policy.status}
                      </Badge>
                    </td>
                    <td className="muted">
                      {policy.updatedAt ? formatTime(policy.updatedAt) : formatTime(policy.createdAt)}
                    </td>
                    <td>
                      <div className="row" style={{ gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
                        <Button variant="ghost" size="sm" onClick={() => setExpanded(policy)}>
                          Rules
                        </Button>
                        {policy.status === 'DRAFT' ? (
                          <>
                            <Button variant="ghost" size="sm" onClick={() => setEditing(policy)}>
                              Edit
                            </Button>
                            <Button
                              variant="primary"
                              size="sm"
                              loading={busy === policy.id}
                              onClick={() => void publish(policy)}
                            >
                              Publish
                            </Button>
                          </>
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

      {expanded ? (
        <Modal
          onClose={() => setExpanded(null)}
          title={`${expanded.name} — v${expanded.version}`}
          description={expanded.description}
          wide
        >
          <div className="col" style={{ gap: 'var(--space-4)' }}>
            <div className="row" style={{ gap: 'var(--space-2)', flexWrap: 'wrap' }}>
              <Badge tone={expanded.status === 'ACTIVE' ? 'allow' : 'approval'}>{expanded.status}</Badge>
              <Badge tone="neutral">default: {expanded.defaultEffect}</Badge>
              <Badge tone="neutral">{expanded.rules.length} rules</Badge>
            </div>

            {expanded.rules.length === 0 ? (
              <p className="muted">This policy has no rules. Every action resolves to the default effect.</p>
            ) : (
              <ul className="rule-list">
                {expanded.rules.map((rule) => (
                  <li key={rule.id} className="rule-row">
                    <Badge tone={EFFECT_TONE[rule.effect]}>{rule.effect}</Badge>
                    <div className="grow col" style={{ gap: 2 }}>
                      <span className="mono" style={{ fontSize: 12.5 }}>
                        {rule.id}
                      </span>
                      <span className="muted-strong" style={{ fontSize: 12 }}>
                        {describeRule(rule)}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}

            <div className="code-block">{JSON.stringify(expanded, null, 2)}</div>
          </div>
        </Modal>
      ) : null}

      {editing ? (
        <PolicyEditor
          policy={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onCreate={async (input) => {
            await createPolicy(input)
            setEditing(null)
          }}
        />
      ) : null}
    </div>
  )
}

function describeRule(rule: Policy['rules'][number]): string {
  const parts: string[] = []
  if (rule.agent) parts.push(`agent: ${rule.agent}`)
  if (rule.tool) parts.push(`tool: ${rule.tool}`)
  if (rule.environment) parts.push(`env: ${rule.environment}`)
  if (rule.category) parts.push(`category: ${rule.category}`)
  if (rule.riskMax) parts.push(`risk ≤ ${rule.riskMax}`)
  return parts.length ? parts.join(' · ') : 'matches everything'
}

function blankRule(index: number): PolicyRule {
  return { id: `rule-${index + 1}`, effect: 'ALLOW' }
}

function PolicyEditor({
  policy,
  onClose,
  onCreate,
}: {
  policy: Policy | null
  onClose: () => void
  onCreate: (input: {
    name: string
    description: string
    defaultEffect: PolicyEffect
    rules: PolicyRule[]
  }) => Promise<void>
}) {
  const { updatePolicy } = useData()
  const [name, setName] = useState(policy?.name ?? '')
  const [description, setDescription] = useState(policy?.description ?? '')
  const [defaultEffect, setDefaultEffect] = useState<PolicyEffect>(policy?.defaultEffect ?? 'DENY')
  const [rules, setRules] = useState<PolicyRule[]>(policy?.rules ?? [blankRule(0)])
  const [busy, setBusy] = useState(false)

  const isDraft = policy === null || policy.status === 'DRAFT'

  function updateRule(index: number, patch: Partial<PolicyRule>) {
    setRules((prev) => prev.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)))
  }

  async function save() {
    setBusy(true)
    try {
      const input = { name: name.trim(), description: description.trim(), defaultEffect, rules }
      if (policy === null) {
        await onCreate(input)
      } else {
        await updatePolicy(policy.id, input)
        onClose()
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      onClose={onClose}
      title={policy === null ? 'New policy' : `Edit ${policy.name}`}
      description="Rules are evaluated deterministically. An explicit deny always wins, and an approval never overrides a hard deny."
      wide
    >
      <div className="col" style={{ gap: 'var(--space-4)' }}>
        <div className="grid-2" style={{ gap: 'var(--space-4)' }}>
          <Field label="Policy name">
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Default production policy"
              autoFocus
            />
          </Field>
          <Field label="Default effect" hint="Applied when no rule matches.">
            <select
              className="select"
              value={defaultEffect}
              onChange={(e) => setDefaultEffect(e.target.value as PolicyEffect)}
            >
              {EFFECTS.map((effect) => (
                <option key={effect} value={effect}>
                  {effect}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Field label="Description">
          <input
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What this policy governs and why."
          />
        </Field>

        <div className="col" style={{ gap: 'var(--space-3)' }}>
          <div className="row-between">
            <span className="field__label">Rules</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setRules((prev) => [...prev, blankRule(prev.length)])}
            >
              Add rule
            </Button>
          </div>

          {!isDraft ? (
            <p className="field__hint">
              This policy is published. Create a new draft to change its rules — published versions are
              immutable so the audit trail stays meaningful.
            </p>
          ) : null}

          <div className="col" style={{ gap: 'var(--space-3)' }}>
            {rules.map((rule, index) => (
              <div key={index} className="rule-editor">
                <div className="grid-2" style={{ gap: 'var(--space-2)' }}>
                  <Field label="Rule ID">
                    <input
                      className="input mono"
                      value={rule.id}
                      disabled={!isDraft}
                      onChange={(e) => updateRule(index, { id: e.target.value })}
                    />
                  </Field>
                  <Field label="Effect">
                    <select
                      className="select"
                      value={rule.effect}
                      disabled={!isDraft}
                      onChange={(e) => updateRule(index, { effect: e.target.value as PolicyEffect })}
                    >
                      {EFFECTS.map((effect) => (
                        <option key={effect} value={effect}>
                          {effect}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>

                <div className="grid-2" style={{ gap: 'var(--space-2)' }}>
                  <Field label="Agent" hint="Leave blank to match any agent.">
                    <input
                      className="input"
                      value={rule.agent ?? ''}
                      disabled={!isDraft}
                      placeholder="support-agent"
                      onChange={(e) =>
                        updateRule(index, { agent: e.target.value || undefined })
                      }
                    />
                  </Field>
                  <Field label="Tool" hint="Leave blank to match any tool.">
                    <input
                      className="input"
                      value={rule.tool ?? ''}
                      disabled={!isDraft}
                      placeholder="send_email"
                      onChange={(e) => updateRule(index, { tool: e.target.value || undefined })}
                    />
                  </Field>
                </div>

                <div className="grid-2" style={{ gap: 'var(--space-2)' }}>
                  <Field label="Environment">
                    <select
                      className="select"
                      value={rule.environment ?? ''}
                      disabled={!isDraft}
                      onChange={(e) =>
                        updateRule(index, {
                          environment: (e.target.value || undefined) as PolicyRule['environment'],
                        })
                      }
                    >
                      <option value="">any</option>
                      <option value="dev">dev</option>
                      <option value="staging">staging</option>
                      <option value="prod">prod</option>
                    </select>
                  </Field>
                  <Field label="Tool category">
                    <select
                      className="select"
                      value={rule.category ?? ''}
                      disabled={!isDraft}
                      onChange={(e) =>
                        updateRule(index, {
                          category: (e.target.value || undefined) as PolicyRule['category'],
                        })
                      }
                    >
                      <option value="">any</option>
                      {CATEGORIES.map((category) => (
                        <option key={category} value={category}>
                          {category}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>

                <Field
                  label="Maximum risk"
                  hint="For ALLOW rules: actions above this risk cannot be allowed by this rule."
                >
                  <select
                    className="select"
                    value={rule.riskMax ?? ''}
                    disabled={!isDraft}
                    onChange={(e) =>
                      updateRule(index, {
                        riskMax: (e.target.value || undefined) as PolicyRule['riskMax'],
                      })
                    }
                  >
                    <option value="">no limit</option>
                    {RISK_LEVELS.map((level) => (
                      <option key={level} value={level}>
                        {level}
                      </option>
                    ))}
                  </select>
                </Field>

                {isDraft && rules.length > 1 ? (
                  <div className="row" style={{ justifyContent: 'flex-end' }}>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setRules((prev) => prev.filter((_, i) => i !== index))}
                    >
                      Remove rule
                    </Button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>

        <div className="row" style={{ gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!name.trim() || !isDraft}
            onClick={() => void save()}
          >
            {policy === null ? 'Create draft' : 'Save draft'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
