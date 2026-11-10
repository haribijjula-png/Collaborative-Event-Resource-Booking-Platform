import { useMemo, useState } from 'react'

const DAY = 86400000
const startOfDay = (d) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x }
const addDays = (d, n) => new Date(startOfDay(d).getTime() + n * DAY + (d.getHours() ? 0 : 0))
const sameDay = (a, b) => startOfDay(a).getTime() === startOfDay(b).getTime()
const startOfWeek = (d) => addDays(d, -startOfDay(d).getDay())
const hm = (d) => new Date(d).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

export function rangeFor(view, cursor) {
  if (view === 'day') return [startOfDay(cursor), addDays(cursor, 1)]
  if (view === 'week') { const s = startOfWeek(cursor); return [s, addDays(s, 7)] }
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
  const s = startOfWeek(first)
  return [s, addDays(s, 42)]
}

/** items: [{id, title, start, end, kind: 'event'|'session'|'booking', onClick}] */
export default function Calendar({ items, view, setView, cursor, setCursor }) {
  const [from] = rangeFor(view, cursor)
  const days = useMemo(() => Array.from({ length: view === 'day' ? 1 : view === 'week' ? 7 : 42 }, (_, i) => addDays(from, i)), [view, from.getTime()]) // eslint-disable-line
  const forDay = (d) => items.filter((i) => startOfDay(i.start) <= d && new Date(i.end) > d && (new Date(i.start) < addDays(d, 1))).sort((a, b) => new Date(a.start) - new Date(b.start))

  const shift = (dir) => {
    const c = new Date(cursor)
    if (view === 'month') c.setMonth(c.getMonth() + dir)
    else c.setDate(c.getDate() + dir * (view === 'week' ? 7 : 1))
    setCursor(c)
  }
  const title = view === 'month' ? cursor.toLocaleDateString([], { month: 'long', year: 'numeric' })
    : view === 'week' ? `${days[0].toLocaleDateString([], { month: 'short', day: 'numeric' })} – ${days[6].toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}`
    : cursor.toLocaleDateString([], { dateStyle: 'full' })

  const Chip = ({ i }) => (
    <button className={`chip k-${i.kind}`} onClick={() => i.onClick?.(i)} title={`${i.title} (${hm(i.start)}–${hm(i.end)})`}>
      <b>{hm(i.start)}</b> {i.title}
    </button>
  )

  return (
    <div className="cal">
      <div className="cal-bar">
        <div className="row">
          <button className="btn sm" onClick={() => shift(-1)} aria-label="Previous">‹</button>
          <button className="btn sm" onClick={() => setCursor(new Date())}>Today</button>
          <button className="btn sm" onClick={() => shift(1)} aria-label="Next">›</button>
          <strong className="cal-title">{title}</strong>
        </div>
        <div className="seg" role="tablist">
          {['month', 'week', 'day'].map((v) => (
            <button key={v} role="tab" aria-selected={view === v} className={view === v ? 'on' : ''} onClick={() => setView(v)}>{v[0].toUpperCase() + v.slice(1)}</button>
          ))}
        </div>
      </div>
      <div className="legend"><span className="chip k-event">Event</span><span className="chip k-session">Session</span><span className="chip k-booking">Booking</span></div>
      {view !== 'day' && (
        <div className="cal-head">{days.slice(0, 7).map((d) => <div key={d.getDay()}>{d.toLocaleDateString([], { weekday: 'short' })}</div>)}</div>
      )}
      <div className={`cal-grid ${view}`}>
        {days.map((d) => {
          const list = forDay(d)
          const dim = view === 'month' && d.getMonth() !== cursor.getMonth()
          return (
            <div key={d.getTime()} className={`cal-cell ${dim ? 'dim' : ''} ${sameDay(d, new Date()) ? 'today' : ''}`}>
              <div className="cal-d">{view === 'day' ? '' : d.getDate()}</div>
              {list.slice(0, view === 'month' ? 3 : 50).map((i) => <Chip key={`${i.kind}-${i.id}`} i={i} />)}
              {view === 'month' && list.length > 3 && <button className="more" onClick={() => { setCursor(d); setView('day') }}>+{list.length - 3} more</button>}
              {view === 'day' && !list.length && <p className="muted">Nothing scheduled.</p>}
            </div>
          )
        })}
      </div>
    </div>
  )
}
