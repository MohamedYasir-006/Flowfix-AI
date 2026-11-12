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
import type { Agent, Environment } from '@/types'
import './pages.css'

export function AgentsPage() {
  const { agents, tools, users, loading, error, refresh, setAgentStatus, setAgentTools, createAgent } =
    useData()
  const [showCreate, setShowCreate] = useState(false)
  const [editing, setEditing] = useState<Agent | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  async function toggleStatus(agent: Agent) {
    setBusy(agent.id)
    try {
      await setAgentStatus(agent.id, agent.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="col" style={{ gap: 'var(--space-5)' }}>
      <PageHead
        title="Agents"
        subtitle="Registered AI agents and the tools each one is permitted to call. Unregistered or disabled agents are denied by default."
        action={
          <Button variant="primary" onClick={() => setShowCreate(true)}>
            Register agent
          </Button>
        }
      />

      {loading ? (
        <Skeleton lines={6} height={20} />
      ) : error ? (
        <ErrorState message={error} onRetry={() => void refresh()} />
      ) : agents.length === 0 ? (
        <Card>
          <EmptyState
            title="No agents registered"
            description="Register an agent to provision its credential and grant tool permissions."
            action={
              <Button variant="primary" onClick={() => setShowCreate(true)}>
                Register the first agent
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
                  <th>Agent</th>
                  <th>Owner</th>
                  <th>Environment</th>
                  <th>Tools</th>
                  <th>Last action</th>
                  <th>Status</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {agents.map((agent) => (
                  <tr key={agent.id}>
                    <td>
                      <div className="col" style={{ gap: 1 }}>
                        <span className="table__cell-main">{agent.name}</span>
                        <span className="table__cell-sub mono">{agent.id}</span>
                      </div>
                    </td>
                    <td>{userName(users, agent.ownerUserId)}</td>
                    <td>
                      <Badge tone={agent.environment === 'prod' ? 'critical' : agent.environment === 'staging' ? 'approval' : 'neutral'}>
                        {agent.environment}
                      </Badge>
                    </td>
                    <td>{agent.toolIds.length}</td>
                    <td className="muted">{agent.lastActionAt ? formatTime(agent.lastActionAt) : 'never'}</td>
                    <td>
                      <Badge tone={agent.status === 'ACTIVE' ? 'allow' : 'neutral'}>{agent.status}</Badge>
                    </td>
                    <td>
                      <div className="row" style={{ gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
                        <Button variant="ghost" size="sm" onClick={() => setEditing(agent)}>
                          Permissions
                        </Button>
                        <Button
                          variant={agent.status === 'ACTIVE' ? 'danger' : 'success'}
                          size="sm"
                          loading={busy === agent.id}
                          onClick={() => void toggleStatus(agent)}
                        >
                          {agent.status === 'ACTIVE' ? 'Disable' : 'Enable'}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {showCreate ? (
        <CreateAgentModal
          users={users}
          onClose={() => setShowCreate(false)}
          onCreate={async (input) => {
            await createAgent(input)
            setShowCreate(false)
          }}
        />
      ) : null}

      {editing ? (
        <PermissionsModal
          agent={editing}
          tools={tools}
          onClose={() => setEditing(null)}
          onSave={async (toolIds) => {
            await setAgentTools(editing.id, toolIds)
            setEditing(null)
          }}
        />
      ) : null}
    </div>
  )
}

function CreateAgentModal({
  users,
  onClose,
  onCreate,
}: {
  users: { id: string; displayName: string; email: string; role: string }[]
  onClose: () => void
  onCreate: (input: { name: string; ownerUserId: string; environment: Environment }) => Promise<void>
}) {
  const [name, setName] = useState('')
  const [ownerUserId, setOwnerUserId] = useState(users[0]?.id ?? '')
  const [environment, setEnvironment] = useState<Environment>('prod')
  const [busy, setBusy] = useState(false)

  return (
    <Modal onClose={onClose} title="Register agent" description="Creates the agent identity. Credentials are provisioned separately.">
      <form
        className="col"
        style={{ gap: 'var(--space-4)' }}
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          try {
            await onCreate({ name: name.trim(), ownerUserId, environment })
          } finally {
            setBusy(false)
          }
        }}
      >
        <Field label="Agent name" hint="Must be unique. Use a stable identifier, e.g. support-agent.">
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="support-agent"
            required
            autoFocus
          />
        </Field>
        <Field label="Owner">
          <select className="select" value={ownerUserId} onChange={(e) => setOwnerUserId(e.target.value)}>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.displayName} — {u.role}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Environment" hint="Production agents are subject to the strictest policy rules.">
          <select
            className="select"
            value={environment}
            onChange={(e) => setEnvironment(e.target.value as Environment)}
          >
            <option value="dev">dev</option>
            <option value="staging">staging</option>
            <option value="prod">prod</option>
          </select>
        </Field>
        <div className="row" style={{ gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" loading={busy} disabled={!name.trim() || !ownerUserId}>
            Register agent
          </Button>
        </div>
      </form>
    </Modal>
  )
}

function PermissionsModal({
  agent,
  tools,
  onClose,
  onSave,
}: {
  agent: Agent
  tools: { id: string; name: string; description: string; category: string; defaultRisk: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'; status: string }[]
  onClose: () => void
  onSave: (toolIds: string[]) => Promise<void>
}) {
  const [selected, setSelected] = useState<string[]>(agent.toolIds)
  const [busy, setBusy] = useState(false)

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]))

  return (
    <Modal
      onClose={onClose}
      title={`Tool permissions — ${agent.name}`}
      description="Least privilege: grant only the tools this agent genuinely needs. Unlisted tools are denied."
    >
      <div className="col" style={{ gap: 'var(--space-4)' }}>
        <div className="checkbox-grid">
          {tools.map((tool) => (
            <label key={tool.id} className="checkbox-item">
              <input
                type="checkbox"
                checked={selected.includes(tool.id)}
                onChange={() => toggle(tool.id)}
                disabled={tool.status === 'DISABLED'}
              />
              <span className="grow col" style={{ gap: 0 }}>
                <span className="mono" style={{ fontSize: 12.5 }}>
                  {tool.name}
                </span>
                <span className="muted-strong" style={{ fontSize: 11.5 }}>
                  {tool.category} · {tool.defaultRisk}
                </span>
              </span>
            </label>
          ))}
        </div>
        {tools.every((t) => t.status === 'DISABLED') ? (
          <p className="field__hint">No tools are currently enabled.</p>
        ) : null}
        <div className="row" style={{ gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={busy}
            onClick={async () => {
              setBusy(true)
              try {
                await onSave(selected)
              } finally {
                setBusy(false)
              }
            }}
          >
            Save permissions
          </Button>
        </div>
      </div>
    </Modal>
  )
}

function userName(users: { id: string; displayName: string }[], id: string): string {
  return users.find((u) => u.id === id)?.displayName ?? 'unassigned'
}
