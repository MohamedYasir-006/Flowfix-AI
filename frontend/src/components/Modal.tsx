import type { ReactNode } from 'react'
import './modal.css'

export function Modal({
  children,
  onClose,
  title,
  description,
  wide,
}: {
  children: ReactNode
  onClose: () => void
  title: string
  description?: string
  wide?: boolean
}) {
  return (
    <div
      className="modal-backdrop"
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
    >
      <div
        className={`modal ${wide ? 'modal--wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__head">
          <div className="col" style={{ gap: 2 }}>
            <h2 id="modal-title">{title}</h2>
            {description ? <p className="muted" style={{ fontSize: 12.5 }}>{description}</p> : null}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="modal__body">{children}</div>
      </div>
    </div>
  )
}
