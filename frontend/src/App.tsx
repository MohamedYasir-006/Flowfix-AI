import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/layout'
import { OverviewPage } from '@/pages/OverviewPage'
import { ActivityPage } from '@/pages/ActivityPage'
import { ApprovalsPage } from '@/pages/ApprovalsPage'
import { AgentsPage } from '@/pages/AgentsPage'
import { ToolsPage } from '@/pages/ToolsPage'
import { PoliciesPage } from '@/pages/PoliciesPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { OperationsPage } from '@/pages/OperationsPage'
import { IncidentsPage } from '@/pages/IncidentsPage'
import { ProvenancePage } from '@/pages/ProvenancePage'
import { TransactionsPage } from '@/pages/TransactionsPage'
import { BenchmarksPage } from '@/pages/BenchmarksPage'

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<OverviewPage />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="tools" element={<ToolsPage />} />
        <Route path="policies" element={<PoliciesPage />} />
        <Route path="operations" element={<OperationsPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="provenance" element={<ProvenancePage />} />
        <Route path="transactions" element={<TransactionsPage />} />
        <Route path="benchmarks" element={<BenchmarksPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

function NotFound() {
  return (
    <div className="col" style={{ gap: 'var(--space-3)', alignItems: 'center', padding: 'var(--space-10)' }}>
      <h1 style={{ fontSize: 40, fontWeight: 650 }}>404</h1>
      <p className="muted">This page doesn't exist.</p>
      <Navigate to="/" replace />
    </div>
  )
}
