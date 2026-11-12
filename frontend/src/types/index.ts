export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type Decision = 'ALLOW' | 'DENY' | 'REQUIRE_APPROVAL'
export type AgentStatus = 'ACTIVE' | 'DISABLED'
export type ToolStatus = 'ACTIVE' | 'DISABLED'
export type ToolCategory = 'read' | 'write' | 'external' | 'destructive'
export type PolicyStatus = 'DRAFT' | 'ACTIVE' | 'ARCHIVED'
export type PolicyEffect = 'ALLOW' | 'DENY' | 'REQUIRE_APPROVAL'
export type ApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED' | 'CONSUMED'
export type UserRole = 'ADMIN' | 'APPROVER' | 'AUDITOR' | 'DEVELOPER'
export type UserStatus = 'ACTIVE' | 'DISABLED'
export type Environment = 'dev' | 'staging' | 'prod'
export type EventType = 'decision' | 'approval' | 'execution' | 'admin'

export interface User {
  id: string
  email: string
  displayName: string
  role: UserRole
  status: UserStatus
  createdAt: string
}

export interface Agent {
  id: string
  name: string
  ownerUserId: string
  environment: Environment
  status: AgentStatus
  toolIds: string[]
  createdAt: string
  updatedAt: string
  lastActionAt?: string
}

export interface Tool {
  id: string
  name: string
  description: string
  inputSchema: Record<string, unknown>
  category: ToolCategory
  defaultRisk: RiskLevel
  status: ToolStatus
  createdAt: string
}

export interface PolicyRule {
  id: string
  effect: PolicyEffect
  agent?: string
  tool?: string
  environment?: Environment
  target?: string
  category?: ToolCategory
  riskMax?: RiskLevel
}

export interface Policy {
  id: string
  name: string
  description: string
  version: number
  defaultEffect: PolicyEffect
  rules: PolicyRule[]
  status: PolicyStatus
  createdBy: string
  createdAt: string
  updatedAt?: string
}

export interface RiskAssessment {
  level: RiskLevel
  reasons: string[]
}

export interface PolicyDecision {
  actionId: string
  decision: Decision
  risk: RiskAssessment
  reasonCodes: string[]
  policy: { id: string; version: number }
  approvalId?: string
  expiresAt?: string
}

export interface Approval {
  id: string
  actionId: string
  payloadHash: string
  requestedByAgentId: string
  status: ApprovalStatus
  approverUserId?: string
  expiresAt: string
  decidedAt?: string
  reason: string
  toolName: string
  target: string
  argumentsSummary: Record<string, unknown>
  riskLevel: RiskLevel
  policyVersion: number
  createdAt: string
}

export interface AuditEvent {
  id: string
  eventType: EventType
  actionId: string
  agentId?: string
  agentName?: string
  sessionId?: string
  toolName?: string
  decision?: Decision
  riskLevel?: RiskLevel
  reasonCodes: string[]
  policyId?: string
  policyVersion?: number
  payloadHash?: string
  metadata?: Record<string, unknown>
  createdAt: string
}

export interface OverviewStats {
  activeAgents: number
  totalAgents: number
  actionsToday: number
  blockedToday: number
  pendingApprovals: number
  decisionsToday: { allow: number; deny: number; requireApproval: number }
  recentEvents: AuditEvent[]
}

export interface Settings {
  workspaceName: string
  defaultEnvironment: Environment
  approvalTtlMinutes: number
  retentionDays: number
  redactSecrets: boolean
  redactFields: string[]
  requireApprovalFor: RiskLevel[]
  maxPayloadBytes: number
}

export interface EventFilters {
  decision?: Decision | 'ALL'
  agentId?: string
  toolName?: string
  eventType?: EventType | 'ALL'
  search?: string
}

export interface AgentInput {
  name: string
  ownerUserId: string
  environment: Environment
}

export interface PolicyInput {
  name: string
  description: string
  defaultEffect: PolicyEffect
  rules: PolicyRule[]
}

export interface ApprovalDecisionInput {
  approverUserId: string
  decision: 'APPROVED' | 'REJECTED'
  reason?: string
}
