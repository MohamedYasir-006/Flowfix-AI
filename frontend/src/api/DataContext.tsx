import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import type {
  Agent,
  Approval,
  AuditEvent,
  Decision,
  EventFilters,
  OverviewStats,
  Policy,
  PolicyInput,
  RiskLevel,
  Settings,
  Tool,
  User,
} from '@/types'
import { getApi, getMode } from './client'
import type { DataMode } from '@/types/dataMode'

export type { DataMode } from '@/types/dataMode'

interface Toast {
  id: number
  kind: 'success' | 'error' | 'info'
  message: string
}

interface DataContextValue {
  mode: DataMode
  loading: boolean
  error: string | null
  agents: Agent[]
  tools: Tool[]
  policies: Policy[]
  approvals: Approval[]
  events: AuditEvent[]
  users: User[]
  settings: Settings | null
  overview: OverviewStats | null
  refresh: () => Promise<void>
  refreshEvents: (filters: EventFilters) => Promise<void>
  eventFilters: EventFilters
  setEventFilters: (filters: EventFilters) => void
  createAgent: (input: { name: string; ownerUserId: string; environment: Agent['environment'] }) => Promise<void>
  setAgentStatus: (id: string, status: Agent['status']) => Promise<void>
  setAgentTools: (id: string, toolIds: string[]) => Promise<void>
  createPolicy: (input: PolicyInput) => Promise<void>
  updatePolicy: (id: string, input: PolicyInput) => Promise<void>
  publishPolicy: (id: string) => Promise<void>
  decideApproval: (id: string, decision: 'APPROVED' | 'REJECTED', reason?: string) => Promise<void>
  updateSettings: (patch: Partial<Settings>) => Promise<void>
  resetDemoData: () => void
  toasts: Toast[]
  dismissToast: (id: number) => void
}

const DataContext = createContext<DataContextValue | null>(null)

const EMPTY_FILTERS: EventFilters = {
  decision: 'ALL',
  eventType: 'ALL',
}

export function DataProvider({ children }: { children: ReactNode }) {
  const api = useMemo(() => getApi(), [])
  const mode: DataMode = useMemo(() => getMode(), [])

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [agents, setAgents] = useState<Agent[]>([])
  const [tools, setTools] = useState<Tool[]>([])
  const [policies, setPolicies] = useState<Policy[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [settings, setSettings] = useState<Settings | null>(null)
  const [overview, setOverview] = useState<OverviewStats | null>(null)
  const [eventFilters, setEventFilters] = useState<EventFilters>(EMPTY_FILTERS)
  const [toasts, setToasts] = useState<Toast[]>([])
  const toastCounter = useRef(0)

  const pushToast = useCallback((kind: Toast['kind'], message: string) => {
    const id = ++toastCounter.current
    setToasts((prev) => [...prev.slice(-3), { id, kind, message }])
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 5000)
  }, [])

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const run = useCallback(
    async (fn: () => Promise<void>, onError?: (e: Error) => void) => {
      try {
        setError(null)
        await fn()
      } catch (e) {
        const err = e as Error
        setError(err.message)
        pushToast('error', err.message)
        onError?.(err)
      }
    },
    [pushToast],
  )

  const refreshEvents = useCallback(
    async (filters: EventFilters = EMPTY_FILTERS) => {
      const data = await api.listEvents(filters)
      setEvents(data)
    },
    [api],
  )

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [agentList, toolList, policyList, approvalList, userList, settingsValue, overviewValue] =
        await Promise.all([
          api.listAgents(),
          api.listTools(),
          api.listPolicies(),
          api.listApprovals(),
          api.listUsers(),
          api.getSettings().catch(() => null),
          api.overview().catch(() => null),
        ])
      setAgents(agentList)
      setTools(toolList)
      setPolicies(policyList)
      setApprovals(approvalList)
      setUsers(userList)
      setSettings(settingsValue)
      setOverview(overviewValue)
      setError(null)
    } catch (e) {
      const err = e as Error
      setError(err.message)
      pushToast('error', err.message)
    } finally {
      setLoading(false)
    }
    await refreshEvents(eventFilters)
  }, [api, eventFilters, pushToast, refreshEvents])

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    void refreshEvents(eventFilters)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventFilters])

  const createAgent: DataContextValue['createAgent'] = useCallback(
    async (input) => {
      await run(async () => {
        const agent = await api.createAgent(input)
        pushToast('success', `Agent "${agent.name}" registered`)
      })
      await refresh()
    },
    [api, pushToast, refresh, run],
  )

  const setAgentStatus: DataContextValue['setAgentStatus'] = useCallback(
    async (id, status) => {
      await run(async () => {
        const agent = await api.setAgentStatus(id, status)
        pushToast('success', `${agent.name} is now ${status.toLowerCase()}`)
      })
      await refresh()
    },
    [api, pushToast, refresh, run],
  )

  const setAgentTools: DataContextValue['setAgentTools'] = useCallback(
    async (id, toolIds) => {
      await run(async () => {
        await api.setAgentTools(id, toolIds)
        pushToast('success', 'Tool permissions updated')
      })
      await refresh()
    },
    [api, pushToast, refresh, run],
  )

  const publishPolicy: DataContextValue['publishPolicy'] = useCallback(
    async (id) => {
      await run(async () => {
        const policy = await api.publishPolicy(id)
        pushToast('success', `"${policy.name}" published as v${policy.version}`)
      })
      await refresh()
    },
    [api, pushToast, refresh, run],
  )

  const createPolicy: DataContextValue['createPolicy'] = useCallback(
    async (input) => {
      await run(async () => {
        const policy = await api.createPolicy(input)
        pushToast('success', `Policy "${policy.name}" created as a draft`)
      })
      await refresh()
    },
    [api, pushToast, refresh, run],
  )

  const updatePolicy: DataContextValue['updatePolicy'] = useCallback(
    async (id, input) => {
      await run(async () => {
        const policy = await api.updatePolicy(id, input)
        pushToast('success', `Policy "${policy.name}" saved`)
      })
      await refresh()
    },
    [api, pushToast, refresh, run],
  )

  const decideApproval: DataContextValue['decideApproval'] = useCallback(
    async (id, decision, reason) => {
      await run(async () => {
        await api.decideApproval(id, {
          approverUserId: 'u-approver',
          decision,
          reason,
        })
        pushToast('success', `Approval ${decision === 'APPROVED' ? 'granted' : 'rejected'}`)
      })
      await refresh()
    },
    [api, pushToast, refresh, run],
  )

  const updateSettings: DataContextValue['updateSettings'] = useCallback(
    async (patch) => {
      await run(async () => {
        const next = await api.updateSettings(patch)
        setSettings(next)
        pushToast('success', 'Settings saved')
      })
    },
    [api, pushToast, run],
  )

  const resetDemoData = useCallback(() => {
    api.resetDemoData()
    void refresh()
    pushToast('info', 'Demo data restored to its initial state')
  }, [api, pushToast, refresh])

  const value: DataContextValue = {
    mode,
    loading,
    error,
    agents,
    tools,
    policies,
    approvals,
    events,
    users,
    settings,
    overview,
    refresh,
    refreshEvents,
    eventFilters,
    setEventFilters,
    createAgent,
    setAgentStatus,
    setAgentTools,
    createPolicy,
    updatePolicy,
    publishPolicy,
    decideApproval,
    updateSettings,
    resetDemoData,
    toasts,
    dismissToast,
  }

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>
}

export function useData(): DataContextValue {
  const ctx = useContext(DataContext)
  if (!ctx) throw new Error('useData must be used inside <DataProvider>')
  return ctx
}

export { type Decision, type RiskLevel }
