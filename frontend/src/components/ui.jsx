import { useEffect } from 'react'
import { useStore } from '../store'
import { label } from '../utils'

export const Spinner = ({ text = 'Loading…' }) => (
  <div className="center muted" role="status"><span className="spinner" /> {text}</div>
)
export const ErrorBox = ({ error, onRetry }) => error ? (
  <div className="alert error" role="alert">{error}{onRetry && <button className="btn sm" onClick={onRetry}>Retry</button>}</div>
) : null
export const Empty = ({ title = 'Nothing here yet', hint }) => (
  <div className="empty"><div className="empty-icon">∅</div><strong>{title}</strong>{hint && <p className="muted">{hint}</p>}</div>
)
export const Badge = ({ value }) => <span className={`badge b-${value}`}>{label(value)}</span>
export const Card = ({ title, actions, children, className = '' }) => (
  <section className={`card ${className}`}>
    {(title || actions) && <header className="card-h"><h3>{title}</h3><div className="row">{actions}</div></header>}
    {children}
  </section>
)

export function Modal({ title, onClose, children, footer }) {
  useEffect(() => {
    const h = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div className="overlay" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}>
        <header className="card-h"><h3>{title}</h3><button className="btn ghost" aria-label="Close" onClick={onClose}>✕</button></header>
        <div className="modal-b">{children}</div>
        {footer && <footer className="modal-f">{footer}</footer>}
      </div>
    </div>
  )
}

export function Field({ label: lbl, error, children, hint }) {
  return (
    <label className="field">
      <span>{lbl}</span>
      {children}
      {hint && !error && <small className="muted">{hint}</small>}
      {error && <small className="err">{error}</small>}
    </label>
  )
}

export function Pagination({ data, onPage }) {
  if (!data || data.pages <= 1) return data ? <div className="muted pg">{data.total} result{data.total === 1 ? '' : 's'}</div> : null
  return (
    <div className="pg">
      <span className="muted">{data.total} results · page {data.page} of {data.pages}</span>
      <div className="row">
        <button className="btn sm" disabled={data.page <= 1} onClick={() => onPage(data.page - 1)}>← Prev</button>
        <button className="btn sm" disabled={data.page >= data.pages} onClick={() => onPage(data.page + 1)}>Next →</button>
      </div>
    </div>
  )
}

export function Toasts() {
  const toasts = useStore((s) => s.toasts)
  return <div className="toasts" aria-live="polite">{toasts.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.message}</div>)}</div>
}

export function BarChart({ data, title }) {
  const entries = Object.entries(data || {})
  const max = Math.max(1, ...entries.map(([, v]) => v))
  if (!entries.length) return <Empty title="No data" />
  return (
    <div className="chart" aria-label={title}>
      {entries.map(([k, v]) => (
        <div className="bar-row" key={k}>
          <span className="bar-l">{label(k)}</span>
          <div className="bar-t"><div className={`bar b-${k}`} style={{ width: `${(v / max) * 100}%` }} /></div>
          <span className="bar-v">{v}</span>
        </div>
      ))}
    </div>
  )
}
