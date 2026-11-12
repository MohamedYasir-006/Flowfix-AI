import type { AuditEvent } from '@/types'

/**
 * Shared presentation helpers for the dashboard. Kept out of component files
 * so React Fast Refresh sees only component exports.
 */

export function formatTime(isoString: string): string {
  const then = new Date(isoString).getTime()
  const diff = Date.now() - then
  const minutes = Math.round(diff / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days}d ago`
  return new Date(isoString).toLocaleDateString()
}

export function agentName(agents: { id: string; name: string }[], id: string): string {
  return agents.find((a) => a.id === id)?.name ?? 'unknown agent'
}

export function userName(users: { id: string; displayName: string }[], id: string): string {
  return users.find((u) => u.id === id)?.displayName ?? 'unassigned'
}

export function userRole(users: { id: string; role: string }[], id: string): string {
  return users.find((u) => u.id === id)?.role ?? '—'
}

/** Compact summary of an event's most useful fields, for list rendering. */
export function eventSummary(event: AuditEvent): string {
  return [event.agentName, event.toolName, event.decision, ...event.reasonCodes]
    .filter(Boolean)
    .join(' ')
}
