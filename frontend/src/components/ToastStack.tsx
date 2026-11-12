import { useData } from '@/api/DataContext'

export function ToastStack() {
  const { toasts, dismissToast } = useData()
  if (toasts.length === 0) return null
  return (
    <div className="toast-stack" role="region" aria-label="Notifications" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.kind}`} role={t.kind === 'error' ? 'alert' : 'status'}>
          <span className="grow">{t.message}</span>
          <button
            className="toast__close"
            onClick={() => dismissToast(t.id)}
            aria-label="Dismiss notification"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
