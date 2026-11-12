import { useState } from 'react'
import { useData } from '@/api/DataContext'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  Field,
  Toggle,
} from '@/components/ui'
import { PageHead } from './OverviewPage'
import type { RiskLevel } from '@/types'
import './pages.css'

const RISK_LEVELS: RiskLevel[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
const DEFAULT_REDACT_FIELDS = ['password', 'token', 'api_key', 'authorization', 'secret']

export function SettingsPage() {
  const { settings, updateSettings, users, resetDemoData, mode } = useData()
  const [workspaceName, setWorkspaceName] = useState(settings?.workspaceName ?? '')
  const [retentionDays, setRetentionDays] = useState(String(settings?.retentionDays ?? 90))
  const [approvalTtl, setApprovalTtl] = useState(String(settings?.approvalTtlMinutes ?? 240))
  const [maxPayload, setMaxPayload] = useState(String(settings?.maxPayloadBytes ?? 65536))
  const [redactFields, setRedactFields] = useState(
    settings?.redactFields.join(', ') ?? DEFAULT_REDACT_FIELDS.join(', '),
  )
  const [busy, setBusy] = useState(false)

  if (!settings) return null

  const current = settings
  const requireApprovalFor = current.requireApprovalFor

  async function save() {
    setBusy(true)
    try {
      await updateSettings({
        workspaceName: workspaceName.trim() || current.workspaceName,
        retentionDays: Number(retentionDays) || current.retentionDays,
        approvalTtlMinutes: Number(approvalTtl) || current.approvalTtlMinutes,
        maxPayloadBytes: Number(maxPayload) || current.maxPayloadBytes,
        redactFields: redactFields
          .split(',')
          .map((f) => f.trim().toLowerCase())
          .filter(Boolean),
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="col" style={{ gap: 'var(--space-5)' }}>
      <PageHead
        title="Settings"
        subtitle="Workspace configuration, retention, redaction, and the risk levels that trigger human approval."
        action={
          <Button variant="primary" loading={busy} onClick={() => void save()}>
            Save settings
          </Button>
        }
      />

      <Card>
        <CardHeader title="Workspace" subtitle="Identity and scope of this AgentGuard instance." />
        <div className="col" style={{ gap: 'var(--space-4)', maxWidth: 520 }}>
          <Field label="Workspace name">
            <input
              className="input"
              value={workspaceName}
              onChange={(e) => setWorkspaceName(e.target.value)}
            />
          </Field>
          <Field label="Data mode">
            <div className="row" style={{ gap: 'var(--space-2)' }}>
              <Badge tone={mode === 'mock' ? 'approval' : 'allow'}>
                {mode === 'mock' ? 'Demo data (in-browser mock)' : 'Live AgentGuard API'}
              </Badge>
              {mode === 'mock' ? (
                <Button variant="ghost" size="sm" onClick={resetDemoData}>
                  Reset demo data
                </Button>
              ) : null}
            </div>
          </Field>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Approval policy"
          subtitle="Which risk levels must be reviewed by a human before execution, and how long an approval stays valid."
        />
        <div className="col" style={{ gap: 'var(--space-4)', maxWidth: 620 }}>
          <div className="col" style={{ gap: 'var(--space-2)' }}>
            <span className="field__label">Require approval for</span>
            <div className="checkbox-grid">
              {RISK_LEVELS.map((level) => (
                <label key={level} className="checkbox-item">
                  <input
                    type="checkbox"
                    checked={requireApprovalFor.includes(level)}
                    onChange={(e) => {
                      const next = e.target.checked
                        ? [...requireApprovalFor, level]
                        : requireApprovalFor.filter((l) => l !== level)
                      void updateSettings({ requireApprovalFor: next })
                    }}
                  />
                  <span>{level}</span>
                </label>
              ))}
            </div>
            <p className="field__hint">
              Deterministic deny rules always win — an approval can never override a hard deny.
            </p>
          </div>

          <div className="grid-2" style={{ gap: 'var(--space-4)' }}>
            <Field label="Approval time-to-live (minutes)" hint="Approvals expire automatically and cannot be reused.">
              <input
                className="input"
                type="number"
                min={5}
                value={approvalTtl}
                onChange={(e) => setApprovalTtl(e.target.value)}
              />
            </Field>
            <Field label="Maximum payload (bytes)" hint="Larger tool arguments are rejected before evaluation.">
              <input
                className="input"
                type="number"
                min={1024}
                step={1024}
                value={maxPayload}
                onChange={(e) => setMaxPayload(e.target.value)}
              />
            </Field>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Privacy and retention"
          subtitle="Secrets are redacted before anything is written to the audit trail."
        />
        <div className="col" style={{ gap: 'var(--space-4)', maxWidth: 620 }}>
          <Toggle
            checked={settings.redactSecrets}
            onChange={(next) => void updateSettings({ redactSecrets: next })}
            label="Redact secrets in the audit trail"
            description="Applies the field list below to every stored event and API response."
          />
          <Field
            label="Redacted fields"
            hint="Comma-separated field names. Matched keys are replaced with [redacted] before persistence."
          >
            <textarea
              className="textarea"
              value={redactFields}
              onChange={(e) => setRedactFields(e.target.value)}
            />
          </Field>
          <Field label="Retention period (days)" hint="Audit records older than this are purged.">
            <input
              className="input"
              type="number"
              min={1}
              value={retentionDays}
              onChange={(e) => setRetentionDays(e.target.value)}
            />
          </Field>
        </div>
      </Card>

      <Card>
        <CardHeader title="Users and roles" subtitle="Who can administer, approve, audit, and develop against this workspace." />
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>User</th>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.displayName}</td>
                  <td className="muted mono" style={{ fontSize: 12.5 }}>{u.email}</td>
                  <td>
                    <Badge
                      tone={
                        u.role === 'ADMIN'
                          ? 'critical'
                          : u.role === 'APPROVER'
                            ? 'approval'
                            : u.role === 'AUDITOR'
                              ? 'info'
                              : 'neutral'
                      }
                    >
                      {u.role}
                    </Badge>
                  </td>
                  <td>
                    <Badge tone={u.status === 'ACTIVE' ? 'allow' : 'neutral'}>{u.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
