import type { ButtonHTMLAttributes, ReactNode } from 'react'
import './ui.css'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'
type Size = 'sm' | 'md'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  fullWidth?: boolean
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  fullWidth = false,
  disabled,
  className = '',
  children,
  ...rest
}: ButtonProps) {
  const classes = [
    'btn',
    `btn--${variant}`,
    `btn--${size}`,
    fullWidth ? 'btn--full' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <button className={classes} disabled={disabled || loading} {...rest}>
      {loading ? <span className="spinner spinner--sm" aria-hidden /> : null}
      {children}
    </button>
  )
}

export function Badge({
  children,
  tone = 'neutral',
  className = '',
}: {
  children: ReactNode
  tone?: 'neutral' | 'allow' | 'deny' | 'approval' | 'info' | 'warn' | 'critical'
  className?: string
}) {
  return <span className={`badge badge--${tone} ${className}`}>{children}</span>
}

export function DecisionBadge({ decision }: { decision: 'ALLOW' | 'DENY' | 'REQUIRE_APPROVAL' }) {
  if (decision === 'ALLOW') return <Badge tone="allow">Allowed</Badge>
  if (decision === 'DENY') return <Badge tone="deny">Blocked</Badge>
  return <Badge tone="approval">Waiting for approval</Badge>
}

export function RiskBadge({ level }: { level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' }) {
  const tone =
    level === 'LOW'
      ? 'allow'
      : level === 'MEDIUM'
        ? 'approval'
        : level === 'HIGH'
          ? 'warn'
          : 'critical'
  return <Badge tone={tone}>{level}</Badge>
}

export function StatusDot({ status }: { status: string }) {
  const active = status === 'ACTIVE' || status === 'APPROVED' || status === 'ALLOW'
  return (
    <span className="status-row">
      <span className={`status-dot ${active ? 'status-dot--on' : 'status-dot--off'}`} aria-hidden />
      {status === 'ACTIVE' ? 'Active' : status === 'DISABLED' ? 'Disabled' : status}
    </span>
  )
}

export function Card({
  children,
  className = '',
  as: Tag = 'section',
}: {
  children: ReactNode
  className?: string
  as?: 'section' | 'div' | 'article'
}) {
  return <Tag className={`card ${className}`}>{children}</Tag>
}

export function CardHeader({
  title,
  subtitle,
  action,
}: {
  title: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="card__header">
      <div className="col" style={{ gap: '2px' }}>
        <h2>{title}</h2>
        {subtitle ? <p className="muted" style={{ fontSize: 13 }}>{subtitle}</p> : null}
      </div>
      {action}
    </div>
  )
}

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: string
  hint?: string
  children: ReactNode
  htmlFor?: string
}) {
  return (
    <div className="field">
      <label className="field__label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {hint ? <p className="field__hint">{hint}</p> : null}
    </div>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
  description?: string
}) {
  return (
    <label className="toggle">
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="toggle__track" aria-hidden>
        <span className="toggle__thumb" />
      </span>
      <span className="toggle__text">
        <span className="toggle__label">{label}</span>
        {description ? <span className="toggle__desc">{description}</span> : null}
      </span>
    </label>
  )
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="empty">
      {icon ? <div className="empty__icon" aria-hidden>{icon}</div> : null}
      <h3>{title}</h3>
      {description ? <p className="muted">{description}</p> : null}
      {action ? <div className="row" style={{ marginTop: 'var(--space-4)' }}>{action}</div> : null}
    </div>
  )
}

export function Skeleton({ lines = 3, height = 16 }: { lines?: number; height?: number }) {
  return (
    <div className="skeleton-group" aria-hidden>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="skeleton"
          style={{ height, width: `${Math.max(45, 100 - i * 12)}%` }}
        />
      ))}
    </div>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden />
      <span className="muted">{label}…</span>
    </div>
  )
}

export function ErrorState({
  title = 'Something went wrong',
  message,
  onRetry,
}: {
  title?: string
  message: string
  onRetry?: () => void
}) {
  return (
    <div className="empty" role="alert">
      <div className="empty__icon" aria-hidden>
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--deny)" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 8v4M12 16h.01" strokeLinecap="round" />
        </svg>
      </div>
      <h3>{title}</h3>
      <p className="muted">{message}</p>
      {onRetry ? (
        <div className="row" style={{ marginTop: 'var(--space-4)' }}>
          <Button variant="primary" onClick={onRetry}>
            Retry
          </Button>
        </div>
      ) : null}
    </div>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>
}
