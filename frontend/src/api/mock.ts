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
  RiskLevel,
  Settings,
  Tool,
  User,
} from '@/types'
import { resetSeed } from './mockData'

export class ApiError extends Error {
  status: number | undefined
  detail: unknown

  constructor(message: string, status?: number, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/**
 * In-memory store backing the mock API. Mirrors the blueprint's data model:
 * users, agents, tools, policies, approvals, audit events, settings.
 */
export class Store {
  users: User[]
  tools: Tool[]
  agents: Agent[]
  policies: Policy[]
  approvals: Approval[]
  events: AuditEvent[]
  settings: Settings

  constructor() {
    const seed = resetSeed()
    this.users = seed.users
    this.tools = seed.tools
    this.agents = seed.agents
    this.policies = seed.policies
    this.approvals = seed.approvals
    this.events = seed.events
    this.settings = seed.settings
  }
  reset() {
    const seed = resetSeed()
    this.users = seed.users
    this.tools = seed.tools
    this.agents = seed.agents
    this.policies = seed.policies
    this.approvals = seed.approvals
    this.events = seed.events
    this.settings = seed.settings
  }

  findAgent(id: string): Agent | undefined {
    return this.agents.find((a) => a.id === id)
  }

  findTool(id: string): Tool | undefined {
    return this.tools.find((t) => t.id === id)
  }

  findToolByName(name: string): Tool | undefined {
    return this.tools.find((t) => t.name === name)
  }

  findPolicy(id: string): Policy | undefined {
    return this.policies.find((p) => p.id === id)
  }

  findApproval(id: string): Approval | undefined {
    return this.approvals.find((a) => a.id === id)
  }

  findUser(id: string): User | undefined {
    return this.users.find((u) => u.id === id)
  }

  /**
   * Deterministic policy evaluation, matching the blueprint's precedence:
   * disabled agent → disabled/unregistered tool → missing permission →
   * explicit deny → approval rule → matching allow → default deny.
   */
  evaluate(input: {
    agentId: string
    toolName: string
    environment?: string
    category?: string
  }): {
    decision: 'ALLOW' | 'DENY' | 'REQUIRE_APPROVAL'
    reasonCodes: string[]
    riskLevel: RiskLevel
    policyId?: string
    policyVersion?: number
  } {
    const agent = this.findAgent(input.agentId)
    const tool = this.findToolByName(input.toolName)
    const policy = this.policies.find((p) => p.status === 'ACTIVE')
    const base = { policyId: policy?.id, policyVersion: policy?.version }

    if (!agent) return { decision: 'DENY', reasonCodes: ['AGENT_NOT_REGISTERED'], riskLevel: 'HIGH', ...base }
    if (agent.status === 'DISABLED') return { decision: 'DENY', reasonCodes: ['AGENT_DISABLED'], riskLevel: 'HIGH', ...base }
    if (!tool) return { decision: 'DENY', reasonCodes: ['TOOL_NOT_REGISTERED'], riskLevel: 'HIGH', ...base }
    if (tool.status === 'DISABLED') return { decision: 'DENY', reasonCodes: ['TOOL_DISABLED'], riskLevel: 'HIGH', ...base }
    if (!agent.toolIds.includes(tool.id)) return { decision: 'DENY', reasonCodes: ['PERMISSION_MISSING'], riskLevel: 'MEDIUM', ...base }

    if (!policy) return { decision: 'DENY', reasonCodes: ['NO_ACTIVE_POLICY'], riskLevel: 'HIGH', ...base }

    const matches = (rule: Policy['rules'][number]) =>
      (!rule.agent || rule.agent === agent.name) &&
      (!rule.tool || rule.tool === tool.name) &&
      (!rule.environment || rule.environment === agent.environment) &&
      (!rule.target || input.toolName === rule.target) &&
      (!rule.category || rule.category === tool.category)

    const matching = policy.rules.filter(matches)
    const deny = matching.find((r) => r.effect === 'DENY')
    if (deny) {
      const codes = ['EXPLICIT_DENY_RULE']
      if (tool.category === 'destructive') codes.push('DESTRUCTIVE_OPERATION')
      return { decision: 'DENY', reasonCodes: codes, riskLevel: tool.defaultRisk, ...base }
    }

    const approval = matching.find((r) => r.effect === 'REQUIRE_APPROVAL')
    if (approval) {
      return {
        decision: 'REQUIRE_APPROVAL',
        reasonCodes: ['POLICY_APPROVAL_REQUIRED', tool.category === 'external' ? 'EXTERNAL_COMMUNICATION' : 'PROTECTED_ACTION'],
        riskLevel: tool.defaultRisk,
        ...base,
      }
    }

    const allow = matching.find((r) => r.effect === 'ALLOW')
    if (allow) {
      const codes = ['TOOL_REGISTERED', 'PERMISSION_GRANTED']
      if (allow.riskMax && tool.defaultRisk !== allow.riskMax) codes.push('RISK_WITHIN_LIMIT')
      return { decision: 'ALLOW', reasonCodes: codes, riskLevel: tool.defaultRisk, ...base }
    }

    return { decision: 'DENY', reasonCodes: ['NO_MATCHING_ALLOW_RULE', 'DEFAULT_DENY'], riskLevel: tool.defaultRisk, ...base }
  }

  overview(): OverviewStats {
    const startOfDay = new Date()
    startOfDay.setHours(0, 0, 0, 0)
    const today = this.events.filter((e) => new Date(e.createdAt) >= startOfDay)
    const decisions = today.filter((e) => e.eventType === 'decision')
    return {
      activeAgents: this.agents.filter((a) => a.status === 'ACTIVE').length,
      totalAgents: this.agents.length,
      actionsToday: decisions.length,
      blockedToday: decisions.filter((e) => e.decision === 'DENY').length,
      pendingApprovals: this.approvals.filter((a) => a.status === 'PENDING').length,
      decisionsToday: {
        allow: decisions.filter((e) => e.decision === 'ALLOW').length,
        deny: decisions.filter((e) => e.decision === 'DENY').length,
        requireApproval: decisions.filter((e) => e.decision === 'REQUIRE_APPROVAL').length,
      },
      recentEvents: [...this.events].sort((a, b) => b.createdAt.localeCompare(a.createdAt)).slice(0, 8),
    }
  }

  filterEvents(filters: EventFilters): AuditEvent[] {
    const search = filters.search?.trim().toLowerCase()
    return this.events
      .filter((e) => (filters.decision && filters.decision !== 'ALL' ? e.decision === filters.decision : true))
      .filter((e) => (filters.agentId ? e.agentId === filters.agentId : true))
      .filter((e) => (filters.toolName ? e.toolName === filters.toolName : true))
      .filter((e) => (filters.eventType && filters.eventType !== 'ALL' ? e.eventType === filters.eventType : true))
      .filter((e) => {
        if (!search) return true
        const haystack = [e.agentName, e.toolName, e.actionId, e.decision, ...e.reasonCodes]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
        return haystack.includes(search)
      })
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  }
}

export const store = new Store()

let counter = 3000
const nextId = (prefix: string) => `${prefix}-${counter++}`

const delay = (ms = 60) => new Promise((r) => setTimeout(r, ms))

/** Mock API: same surface as the planned /api/v1 endpoints. */
export const mockApi = {
  async listAgents(): Promise<Agent[]> {
    await delay()
    return [...store.agents].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  },

  async createAgent(input: AgentInput): Promise<Agent> {
    await delay()
    if (store.agents.some((a) => a.name === input.name)) {
      throw new ApiError(`Agent name "${input.name}" is already registered`, 409)
    }
    const agent: Agent = {
      id: nextId('agent'),
      name: input.name,
      ownerUserId: input.ownerUserId,
      environment: input.environment,
      status: 'ACTIVE',
      toolIds: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
    store.agents.push(agent)
    store.events.unshift({
      id: nextId('evt'),
      eventType: 'admin',
      actionId: nextId('act'),
      agentId: agent.id,
      agentName: agent.name,
      reasonCodes: ['AGENT_REGISTERED'],
      metadata: { actorUserId: input.ownerUserId, environment: input.environment },
      createdAt: agent.createdAt,
    })
    return agent
  },

  async setAgentStatus(id: string, status: Agent['status']): Promise<Agent> {
    await delay()
    const agent = store.findAgent(id)
    if (!agent) throw new ApiError('Agent not found', 404)
    agent.status = status
    agent.updatedAt = new Date().toISOString()
    store.events.unshift({
      id: nextId('evt'),
      eventType: 'admin',
      actionId: nextId('act'),
      agentId: agent.id,
      agentName: agent.name,
      reasonCodes: [status === 'DISABLED' ? 'AGENT_DISABLED_BY_ADMIN' : 'AGENT_ENABLED_BY_ADMIN'],
      metadata: { actorUserId: 'u-admin', previousStatus: status === 'DISABLED' ? 'ACTIVE' : 'DISABLED' },
      createdAt: agent.updatedAt,
    })
    return agent
  },

  async setAgentTools(id: string, toolIds: string[]): Promise<Agent> {
    await delay()
    const agent = store.findAgent(id)
    if (!agent) throw new ApiError('Agent not found', 404)
    agent.toolIds = [...new Set(toolIds)]
    agent.updatedAt = new Date().toISOString()
    return agent
  },

  async listTools(): Promise<Tool[]> {
    await delay()
    return [...store.tools].sort((a, b) => a.name.localeCompare(b.name))
  },

  async listPolicies(): Promise<Policy[]> {
    await delay()
    return [...store.policies].sort((a, b) => b.version - a.version)
  },

  async createPolicy(input: PolicyInput): Promise<Policy> {
    await delay()
    const maxVersion = store.policies.reduce((max, p) => Math.max(max, p.version), 0)
    const policy: Policy = {
      id: nextId('policy'),
      name: input.name,
      description: input.description,
      version: maxVersion + 1,
      defaultEffect: input.defaultEffect,
      rules: input.rules.map((rule, index) => ({
        ...rule,
        id: rule.id || `rule-${index + 1}`,
      })),
      status: 'DRAFT',
      createdBy: 'u-admin',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
    store.policies.push(policy)
    store.events.unshift({
      id: nextId('evt'),
      eventType: 'admin',
      actionId: nextId('act'),
      reasonCodes: ['POLICY_CREATED'],
      policyId: policy.id,
      policyVersion: policy.version,
      metadata: { actorUserId: 'u-admin', status: policy.status },
      createdAt: policy.createdAt,
    })
    return policy
  },

  async updatePolicy(id: string, input: PolicyInput): Promise<Policy> {
    await delay()
    const policy = store.findPolicy(id)
    if (!policy) throw new ApiError('Policy not found', 404)
    if (policy.status !== 'DRAFT') {
      throw new ApiError('Only draft policies can be edited', 409)
    }
    policy.name = input.name
    policy.description = input.description
    policy.defaultEffect = input.defaultEffect
    policy.rules = input.rules.map((rule, index) => ({
      ...rule,
      id: rule.id || `rule-${index + 1}`,
    }))
    policy.updatedAt = new Date().toISOString()
    return policy
  },

  async publishPolicy(id: string): Promise<Policy> {
    await delay()
    const policy = store.findPolicy(id)
    if (!policy) throw new ApiError('Policy not found', 404)
    policy.status = 'ACTIVE'
    policy.version += 1
    policy.updatedAt = new Date().toISOString()
    store.events.unshift({
      id: nextId('evt'),
      eventType: 'admin',
      actionId: nextId('act'),
      reasonCodes: ['POLICY_PUBLISHED'],
      policyId: policy.id,
      policyVersion: policy.version,
      metadata: { actorUserId: 'u-admin', previousVersion: policy.version - 1 },
      createdAt: policy.updatedAt,
    })
    return policy
  },

  async listApprovals(status?: Approval['status']): Promise<Approval[]> {
    await delay()
    return [...store.approvals]
      .filter((a) => (status ? a.status === status : true))
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  },

  async decideApproval(id: string, input: ApprovalDecisionInput): Promise<Approval> {
    await delay()
    const approval = store.findApproval(id)
    if (!approval) throw new ApiError('Approval not found', 404)
    if (approval.status !== 'PENDING') throw new ApiError(`Approval is already ${approval.status.toLowerCase()}`, 409)
    if (new Date(approval.expiresAt).getTime() < Date.now()) {
      approval.status = 'EXPIRED'
      throw new ApiError('Approval has expired', 410)
    }
    const approver = store.findUser(input.approverUserId)
    if (!approver || approver.role !== 'APPROVER') throw new ApiError('Only an authorized approver can decide', 403)

    approval.status = input.decision
    approval.approverUserId = approver.id
    approval.decidedAt = new Date().toISOString()
    store.events.unshift({
      id: nextId('evt'),
      eventType: 'approval',
      actionId: approval.actionId,
      agentId: approval.requestedByAgentId,
      toolName: approval.toolName,
      riskLevel: approval.riskLevel,
      reasonCodes: [input.decision === 'APPROVED' ? 'APPROVAL_GRANTED' : 'APPROVAL_REJECTED'],
      policyId: 'policy-prod',
      policyVersion: approval.policyVersion,
      metadata: { approvalId: approval.id, approverUserId: approver.id, reason: input.reason },
      createdAt: approval.decidedAt,
    })
    return approval
  },

  async listEvents(filters: EventFilters = {}): Promise<AuditEvent[]> {
    await delay()
    return store.filterEvents(filters)
  },

  async overview(): Promise<OverviewStats> {
    await delay()
    return store.overview()
  },

  async listUsers(): Promise<User[]> {
    await delay()
    return [...store.users].sort((a, b) => a.displayName.localeCompare(b.displayName))
  },

  async getSettings(): Promise<Settings> {
    await delay()
    return { ...store.settings }
  },

  async updateSettings(patch: Partial<Settings>): Promise<Settings> {
    await delay()
    store.settings = { ...store.settings, ...patch }
    return { ...store.settings }
  },

  resetDemoData() {
    store.reset()
  },
}
