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

export const httpApi = {
  async listAgents(): Promise<Agent[]> {
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
