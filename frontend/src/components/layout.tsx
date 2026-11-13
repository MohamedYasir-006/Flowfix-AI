import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useData } from '@/api/DataContext'
import { Spinner } from '@/components/ui'
import { ToastStack } from './ToastStack'
import './layout.css'

const NAV = [
  {
    section: 'Monitor',
    items: [
      { to: '/', label: 'Overview', icon: IconGrid, end: true },
      { to: '/activity', label: 'Activity', icon: IconPulse },
      { to: '/approvals', label: 'Approvals', icon: IconCheck, badge: 'pending' },
    ],
  },
  {
    section: 'Govern',
    items: [
      { to: '/agents', label: 'Agents', icon: IconAgent },
      { to: '/tools', label: 'Tools', icon: IconTool },
      { to: '/policies', label: 'Policies', icon: IconShield },
    ],
  },
  {
    section: 'Operate',
    items: [
      { to: '/operations', label: 'Agent health', icon: IconAgent },
      { to: '/provenance', label: 'Provenance', icon: IconPulse },
      { to: '/incidents', label: 'Incidents', icon: IconShield },
      { to: '/transactions', label: 'Transactions', icon: IconTool },
      { to: '/benchmarks', label: 'Benchmarks', icon: IconCheck },
    ],
  },
  {
    section: 'Workspace',
    items: [
      { to: '/settings', label: 'Settings', icon: IconSettings },
    ],
  },
]

export function AppLayout() {
  const { loading, error, pendingCount, mode, refresh } = useShellData()
  const location = useLocation()

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to main content
      </a>

      <aside className="sidebar" aria-label="Primary navigation">
        <div className="sidebar__brand">
          <div className="brand-mark" aria-hidden>
            <svg width="22" height="22" viewBox="0 0 32 32" fill="none">
              <path
                d="M16 4l10 3.8v6.4c0 5.9-4.2 11.1-10 12.9-5.8-1.8-10-7-10-12.9V7.8L16 4z"
                stroke="currentColor"
                strokeWidth="2.4"
              />
              <path
                d="M11.5 16l3.2 3.2 5.6-6.2"
                stroke="var(--allow)"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <div className="col" style={{ gap: 0 }}>
            <span className="brand-name">AgentGuard</span>
            <span className="brand-tag">Agent governance console</span>
          </div>
        </div>

        <nav className="sidebar__nav">
          {NAV.map((group) => (
            <div key={group.section} className="nav-group">
              <p className="nav-group__label">{group.section}</p>
              <ul>
                {group.items.map((item) => (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      end={item.end}
                      className={({ isActive }) =>
                        `nav-item ${isActive ? 'nav-item--active' : ''}`
                      }
                    >
                      <item.icon className="nav-item__icon" />
                      <span className="grow">{item.label}</span>
                      {item.badge === 'pending' && pendingCount > 0 ? (
                        <span className="nav-badge" aria-label={`${pendingCount} pending`}>
                          {pendingCount}
                        </span>
                      ) : null}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <div className="sidebar__footer">
          <div className="row" style={{ gap: 'var(--space-2)' }}>
            <span className={`mode-pill mode-pill--${mode}`}>
              {mode === 'mock' ? 'Demo data' : 'Live API'}
            </span>
          </div>
          <p className="sidebar__note">
            {mode === 'mock'
              ? 'Browsing seeded demo data. Point VITE_USE_MOCK=false at your FastAPI backend to go live.'
              : 'Connected to the AgentGuard API.'}
          </p>
        </div>
      </aside>

      <div className="main-col">
        <header className="topbar">
          <div className="row" style={{ gap: 'var(--space-2)' }}>
            <span className="topbar__crumb muted">{breadcrumbs(location.pathname)}</span>
          </div>
          <div className="row" style={{ gap: 'var(--space-2)' }}>
            {loading ? (
              <span className="row" style={{ gap: 6 }}>
                <Spinner label="" />
              </span>
            ) : (
              <button className="icon-btn" onClick={() => void refresh()} title="Refresh data" aria-label="Refresh data">
                <IconRefresh />
              </button>
            )}
          </div>
        </header>

        <main id="main" className="main" tabIndex={-1}>
          {error && !loading ? (
            <div className="banner banner--error" role="alert">
              <span>{error}</span>
              <button className="banner__action" onClick={() => void refresh()}>
                Retry
              </button>
            </div>
          ) : null}
          <Outlet />
        </main>
      </div>

      <ToastStack />
    </div>
  )
}

function useShellData() {
  const { loading, error, approvals, mode, refresh } = useData()
  return {
    loading,
    error,
    mode,
    refresh,
    pendingCount: approvals.filter((a) => a.status === 'PENDING').length,
  }
}

function breadcrumbs(pathname: string): string {
  if (pathname === '/') return 'Overview'
  return pathname.slice(1).replace(/\//g, ' / ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/* ---------- Icons ---------- */
function IconBase({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <svg
      className={className}
      width="17"
      height="17"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  )
}

function IconGrid({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </IconBase>
  )
}

function IconPulse({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <path d="M3 12h4l2.5-7 4 14 2.5-7h5" />
    </IconBase>
  )
}

function IconCheck({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M8.5 12.2l2.4 2.4 4.6-5" />
    </IconBase>
  )
}

function IconAgent({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <rect x="5" y="7" width="14" height="12" rx="3" />
      <path d="M12 3v4M9.5 13h.01M14.5 13h.01" />
      <path d="M9 17h6" />
    </IconBase>
  )
}

function IconTool({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <path d="M14.5 5.5a4 4 0 0 0-5.6 4.9L4 15.3V19h3.7l4.9-4.9a4 4 0 0 0 4.9-5.6l-2.6 2.6-2.4-.6-.6-2.4 2.6-2.6z" />
    </IconBase>
  )
}

function IconShield({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <path d="M12 3l7 2.8v5.4c0 4.6-3 8.6-7 9.8-4-1.2-7-5.2-7-9.8V5.8L12 3z" />
      <path d="M9 12l2.2 2.2L15.5 10" />
    </IconBase>
  )
}

function IconSettings({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h.1a1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </IconBase>
  )
}

function IconRefresh({ className }: { className?: string }) {
  return (
    <IconBase className={className}>
      <path d="M20 11a8 8 0 1 0-2.3 6.3" />
      <path d="M20 5v6h-6" />
    </IconBase>
  )
}
