import type {
  Agent,
  AgentInput,
  Approval,
  ApprovalDecisionInput,
  AuditEvent,
  EventFilters,
  OverviewStats,
  Policy,
  PolicyInput,
  Settings,
  Tool,
  User,
} from '@/types'
import { ApiError, mockApi } from './mock'
import type { DataMode } from '@/types/dataMode'

/**
 * HTTP client for the AgentGuard FastAPI backend (`/api/v1`).
 *
 * The blueprint's REST contract is implemented here endpoint-for-endpoint so
 * the UI does not change when the backend lands: the mock layer and this
 * client expose the same method signatures.
 *
 * Responses use snake_case from the server; each method maps to the camelCase
 * shapes used by the UI.
 */

const BASE_URL = (
  (import.meta.env?.VITE_API_BASE_URL as string | undefined) ??
  (globalThis as { __AGENTGUARD_API_BASE__?: string }).__AGENTGUARD_API_BASE__ ??
  '/api/v1'
).replace(/\/$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    })
  } catch (error) {
    throw new ApiError(
      `Cannot reach the AgentGuard API at ${BASE_URL}. Start the backend or re-enable the mock data layer.`,
      undefined,
      error,
    )
  }

  if (!response.ok) {
    let detail: unknown = undefined
    try {
      detail = await response.json()
    } catch {
      detail = await response.text().catch(() => undefined)
    }
    const message =
      typeof detail === 'object' && detail !== null && 'detail' in detail
        ? String((detail as { detail: unknown }).detail)
        : response.statusText
    throw new ApiError(message || `Request failed (${response.status})`, response.status, detail)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export interface AgentDto {
  id: string
  name: string
  owner_user_id: string
  environment: string
  status: string
  tool_ids?: string[]
  created_at: string
  updated_at: string
  last_action_at?: string
}

export interface ToolDto {
  id: string
  name: string
  description: string
  input_schema: Record<string, unknown>
  category: string
  default_risk: string
  status: string
  created_at: string
}

export interface PolicyDto {
  id: string
  name: string
  description: string
  version: number
  default_effect: string
  rules: Policy['rules']
  status: string
  created_by: string
  created_at: string
  updated_at?: string
}

export interface ApprovalDto {
  id: string
  action_id: string
  payload_hash: string
  requested_by_agent_id: string
  status: string
  approver_user_id?: string
  expires_at: string
  decided_at?: string
  reason: string
  tool_name: string
  target: string
  arguments_summary: Record<string, unknown>
  risk_level: string
  policy_version: number
  created_at: string
}

export interface EventDto {
  id: string
  event_type: string
  action_id: string
  agent_id?: string
  agent_name?: string
  session_id?: string
  tool_name?: string
  decision?: string
  risk_level?: string
  reason_codes: string[]
  policy_id?: string
  policy_version?: number
  payload_hash?: string
  metadata?: Record<string, unknown>
  created_at: string
}

const toAgent = (d: AgentDto): Agent => ({
  id: d.id,
  name: d.name,
  ownerUserId: d.owner_user_id,
  environment: d.environment as Agent['environment'],
  status: d.status as Agent['status'],
  toolIds: d.tool_ids ?? [],
  createdAt: d.created_at,
  updatedAt: d.updated_at,
  lastActionAt: d.last_action_at,
})

const toTool = (d: ToolDto): Tool => ({
  id: d.id,
  name: d.name,
  description: d.description,
  inputSchema: d.input_schema,
  category: d.category as Tool['category'],
  defaultRisk: d.default_risk as Tool['defaultRisk'],
  status: d.status as Tool['status'],
  createdAt: d.created_at,
})

const toPolicy = (d: PolicyDto): Policy => ({
  id: d.id,
  name: d.name,
  description: d.description,
  version: d.version,
  defaultEffect: d.default_effect as Policy['defaultEffect'],
  rules: d.rules ?? [],
  status: d.status as Policy['status'],
  createdBy: d.created_by,
  createdAt: d.created_at,
  updatedAt: d.updated_at,
})

const toApproval = (d: ApprovalDto): Approval => ({
  id: d.id,
  actionId: d.action_id,
  payloadHash: d.payload_hash,
  requestedByAgentId: d.requested_by_agent_id,
  status: d.status as Approval['status'],
  approverUserId: d.approver_user_id,
  expiresAt: d.expires_at,
  decidedAt: d.decided_at,
  reason: d.reason,
  toolName: d.tool_name,
  target: d.target,
  argumentsSummary: d.arguments_summary ?? {},
  riskLevel: d.risk_level as Approval['riskLevel'],
  policyVersion: d.policy_version,
  createdAt: d.created_at,
})

const toEvent = (d: EventDto): AuditEvent => ({
  id: d.id,
  eventType: d.event_type as AuditEvent['eventType'],
  actionId: d.action_id,
  agentId: d.agent_id,
  agentName: d.agent_name,
  sessionId: d.session_id,
  toolName: d.tool_name,
  decision: d.decision as AuditEvent['decision'],
  riskLevel: d.risk_level as AuditEvent['riskLevel'],
  reasonCodes: d.reason_codes ?? [],
  policyId: d.policy_id,
  policyVersion: d.policy_version,
  payloadHash: d.payload_hash,
  metadata: d.metadata,
  createdAt: d.created_at,
})

const toUser = (d: User & Record<string, unknown>): User => ({
  id: String(d.id),
  email: String(d.email),
  displayName: String(d.display_name ?? d.displayName ?? d.email),
  role: d.role as User['role'],
  status: (d.status as User['status']) ?? 'ACTIVE',
  createdAt: String(d.created_at ?? new Date().toISOString()),
})

export const httpApi = {  async listAgents(): Promise<Agent[]> {
    const data = await request<AgentDto[]>('/agents')
    return data.map(toAgent)
  },

  async createAgent(input: AgentInput): Promise<Agent> {
    const data = await request<AgentDto>('/agents', {
      method: 'POST',
      body: JSON.stringify({
        name: input.name,
        owner_user_id: input.ownerUserId,
        environment: input.environment,
      }),
    })
    return toAgent(data)
  },

  async setAgentStatus(id: string, status: Agent['status']): Promise<Agent> {
    const data = await request<AgentDto>(`/agents/${id}/${status === 'DISABLED' ? 'disable' : 'enable'}`, {
      method: 'POST',
    })
    return toAgent(data)
  },

  async setAgentTools(id: string, toolIds: string[]): Promise<Agent> {
    const data = await request<AgentDto>(`/agents/${id}/permissions`, {
      method: 'PUT',
      body: JSON.stringify({ tool_ids: toolIds }),
    })
    return toAgent(data)
  },

  async listTools(): Promise<Tool[]> {
    const data = await request<ToolDto[]>('/tools')
    return data.map(toTool)
  },

  async listPolicies(): Promise<Policy[]> {
    const data = await request<PolicyDto[]>('/policies')
    return data.map(toPolicy)
  },

  async createPolicy(input: PolicyInput): Promise<Policy> {
    const data = await request<PolicyDto>('/policies', {
      method: 'POST',
      body: JSON.stringify({
        name: input.name,
        description: input.description,
        default_effect: input.defaultEffect,
        rules: input.rules,
      }),
    })
    return toPolicy(data)
  },

  async updatePolicy(id: string, input: PolicyInput): Promise<Policy> {
    const data = await request<PolicyDto>(`/policies/${id}`, {
      method: 'PUT',
      body: JSON.stringify({
        name: input.name,
        description: input.description,
        default_effect: input.defaultEffect,
        rules: input.rules,
      }),
    })
    return toPolicy(data)
  },

  async publishPolicy(id: string): Promise<Policy> {
    const data = await request<PolicyDto>(`/policies/${id}/publish`, { method: 'POST' })
    return toPolicy(data)
  },

  async listApprovals(status?: Approval['status']): Promise<Approval[]> {
    const query = status ? `?status=${status}` : ''
    const data = await request<ApprovalDto[]>(`/approvals${query}`)
    return data.map(toApproval)
  },

  async decideApproval(id: string, input: ApprovalDecisionInput): Promise<Approval> {
    const data = await request<ApprovalDto>(`/approvals/${id}/${input.decision === 'APPROVED' ? 'approve' : 'reject'}`, {
      method: 'POST',
      body: JSON.stringify({
        approver_user_id: input.approverUserId,
        reason: input.reason,
      }),
    })
    return toApproval(data)
  },

  async listEvents(filters: EventFilters = {}): Promise<AuditEvent[]> {
    const params = new URLSearchParams()
    if (filters.decision && filters.decision !== 'ALL') params.set('decision', filters.decision)
    if (filters.agentId) params.set('agent_id', filters.agentId)
    if (filters.toolName) params.set('tool_name', filters.toolName)
    if (filters.eventType && filters.eventType !== 'ALL') params.set('event_type', filters.eventType)
    if (filters.search) params.set('q', filters.search)
    const query = params.toString() ? `?${params}` : ''
    const data = await request<EventDto[]>(`/events${query}`)
    return data.map(toEvent)
  },

  async overview(): Promise<OverviewStats> {
    return request<OverviewStats>('/overview')
  },

  async listUsers(): Promise<User[]> {
    const data = await request<Array<User & Record<string, unknown>>>('/users')
    return data.map(toUser)
  },

  async getSettings(): Promise<Settings> {
    return request<Settings>('/settings')
  },

  async updateSettings(patch: Partial<Settings>): Promise<Settings> {
    return request<Settings>('/settings', { method: 'PATCH', body: JSON.stringify(patch) })
  },

  resetDemoData() {
    return Promise.resolve()
  },
}

export interface AgentHealthDto {
  agent_id: string
  agent_name: string
  status: string
  operational_status: string
  quarantine_reason?: string | null
  quarantined_at?: string | null
  circuit_state: string
  reliability: ReliabilityDto
  recent_failures: number
}

export interface ReliabilityDto {
  agent_id: string
  agent_name: string
  score: number
  confidence: number
  level: string
  observations: number
  window_days: number
  metrics: Record<string, unknown>
  contributing_factors: string[]
  trend: string
  methodology: string
  computed_at: string
}

export interface WorkflowDto {
  id: string
  org_id: string
  name: string
  description: string
  status: string
  created_at: string
  updated_at: string
}

export interface WorkflowExecutionDto {
  id: string
  workflow_id: string
  org_id: string
  external_key?: string | null
  status: string
  started_at: string
  ended_at?: string | null
}

export interface GraphDto {
  workflow_execution_id: string
  nodes: Array<{ id: string; type: string; label: string; status: string; metadata: Record<string, unknown> }>
  edges: Array<{
    id: string
    source: string
    target: string
    relationship: string
    validation_status: string
    artifact_id?: string | null
    created_at: string
  }>
  cycles: string[][]
}

export interface TimelineEntryDto {
  timestamp: string
  kind: string
  actor?: string | null
  summary: string
  evidence_ref?: string | null
  data: Record<string, unknown>
}

export interface IncidentDto {
  id: string
  workflow_execution_id?: string | null
  origin_agent_id?: string | null
  failure_type: string
  risk_level: string
  status: string
  summary: string
  evidence: Record<string, unknown>
  created_at: string
  resolved_at?: string | null
}

export interface IncidentReportDto {
  incident: IncidentDto
  timeline: TimelineEntryDto[]
  affected_agents: string[]
  affected_workflows: string[]
  recommendation: string
}

export interface TransactionStepDto {
  id: string
  transaction_id: string
  step_key: string
  sequence: number
  tool_name: string
  status: string
  action_id?: string | null
  idempotency_key?: string | null
  compensation_tool?: string | null
  compensation_status: string
  attempts: number
  last_error?: string | null
  started_at?: string | null
  completed_at?: string | null
  created_at: string
}

export interface TransactionDto {
  id: string
  workflow_execution_id?: string | null
  status: string
  idempotency_key?: string | null
  created_at: string
  updated_at: string
  steps: TransactionStepDto[]
}

export interface BenchmarkScenarioDto {
  scenario: string
  description: string
  expected_effect: string
  baseline: Record<string, unknown>
  agentguard_v2: Record<string, unknown>
  metrics: Record<string, unknown>
  passed: boolean
}

export interface BenchmarkDto {
  run_id?: string | null
  suite: string
  seed: number
  generated_at: string
  scenarios: BenchmarkScenarioDto[]
  aggregate: Record<string, unknown>
  methodology: string
}

/**
 * V2 operational intelligence endpoints. These are read/control-plane calls
 * against the live API. They are intentionally separate from the V1 data
 * context so existing pages keep working unchanged.
 */
export const v2Api = {
  containmentAgents: () => request<AgentHealthDto[]>('/containment/agents'),
  circuits: () => request<Array<Record<string, unknown>>>('/containment/circuits'),
  notifications: () => request<Array<Record<string, unknown>>>('/notifications'),
  quarantine: (agentId: string, reason: string) =>
    request<AgentHealthDto>(`/agents/${agentId}/quarantine`, {
      method: 'POST',
      body: JSON.stringify({ reason, evidence: {} }),
    }),
  startRecovery: (agentId: string) =>
    request<AgentHealthDto>(`/agents/${agentId}/recovery/start`, {
      method: 'POST',
      body: JSON.stringify({ confirm: true, evidence: {} }),
    }),
  completeRecovery: (agentId: string) =>
    request<AgentHealthDto>(`/agents/${agentId}/recovery/complete`, {
      method: 'POST',
      body: JSON.stringify({ confirm: true, evidence: {} }),
    }),

  workflows: () => request<WorkflowDto[]>('/workflows'),
  executions: () => request<WorkflowExecutionDto[]>('/workflow-executions'),
  executionSummary: (id: string) => request<Record<string, unknown>>(`/workflow-executions/${id}`),
  graph: (id: string) => request<GraphDto>(`/workflow-executions/${id}/graph`),
  timeline: (id: string) => request<TimelineEntryDto[]>(`/workflow-executions/${id}/timeline`),
  lineage: (artifactId: string) => request<Record<string, unknown>>(`/artifacts/${artifactId}/lineage`),
  artifacts: () => request<Array<Record<string, unknown>>>('/artifacts'),

  incidents: (status?: string) =>
    request<IncidentDto[]>(`/incidents${status ? `?status=${status}` : ''}`),
  incidentReport: (id: string) => request<IncidentReportDto>(`/incidents/${id}/report`),
  resolveIncident: (id: string, resolution: string) =>
    request<IncidentDto>(`/incidents/${id}/resolve?resolution=${encodeURIComponent(resolution)}`, {
      method: 'POST',
    }),
  whatIf: (actionId: string, hypotheticalDecision: string) =>
    request<Record<string, unknown>>('/incidents/what-if', {
      method: 'POST',
      body: JSON.stringify({ action_id: actionId, hypothetical_decision: hypotheticalDecision }),
    }),

  transactions: () => request<TransactionDto[]>('/transactions'),
  recoveryPlan: (id: string) => request<Record<string, unknown>>(`/transactions/${id}/recovery-plan`),

  runBenchmark: () =>
    request<BenchmarkDto>('/benchmarks/afpb/run', {
      method: 'POST',
      body: JSON.stringify({ suite: 'AFPB', seed: 7, repetitions: 1 }),
    }),

  auditVerify: () => request<Record<string, unknown>>('/audit/verify'),
}

export type Api = typeof mockApi
export type GuardApi = Api

export function shouldUseMockData(): boolean {
  const flag =
    (import.meta.env?.VITE_USE_MOCK as string | undefined) ??
    (globalThis as { __AGENTGUARD_USE_MOCK__?: string }).__AGENTGUARD_USE_MOCK__
  if (flag !== undefined) return flag !== 'false'
  return true
}

let cached: Api | undefined
let cachedMode: DataMode | undefined

/** Single entry point used by the UI; resolves to mock or HTTP implementation. */
export function getApi(): Api {
  if (!cached) {
    cached = shouldUseMockData() ? mockApi : httpApi
  }
  return cached
}

export function getMode(): DataMode {
  if (!cachedMode) {
    cachedMode = getApi() === mockApi ? 'mock' : 'live'
  }
  return cachedMode
}

export const isLiveMode = () => getMode() === 'live'
export const isMockMode = () => getMode() === 'mock'
