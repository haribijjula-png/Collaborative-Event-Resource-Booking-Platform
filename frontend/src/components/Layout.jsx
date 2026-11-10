import { useEffect, useRef } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import api from '../api'
import { useRole, useStore } from '../store'
import { Toasts } from './ui'

const NAV = [
  ['/', 'Dashboard', 'participant'], ['/calendar', 'Calendar', 'participant'], ['/events', 'Events', 'participant'],
  ['/sessions', 'Sessions', 'participant'], ['/registrations', 'Registrations', 'participant'],
  ['/resources', 'Resources', 'participant'], ['/bookings', 'Bookings', 'staff'], ['/attendance', 'Attendance', 'staff'],
  ['/members', 'Members', 'staff'], ['/organizations', 'Organizations', 'participant'],
  ['/notifications', 'Notifications', 'participant'], ['/profile', 'Profile', 'participant'], ['/settings', 'Settings', 'participant'],
]

export default function Layout() {
  const { user, orgs, activeOrgId, setOrgs, setActiveOrg, logout, unread, setUnread, toast, theme, access } = useStore()
  const { can } = useRole()
  const nav = useNavigate()
  const wsRef = useRef(null)

  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])
  useEffect(() => { api.get('/organizations').then((r) => setOrgs(r.data.data)).catch(() => {}) }, [setOrgs])

  const refreshUnread = () => api.get('/notifications?page_size=1').then((r) => setUnread(r.data.data.unread_count)).catch(() => {})
  useEffect(() => { refreshUnread() }, [])

  // Real-time channel (REST remains the fallback / source of truth).
  useEffect(() => {
    if (!access) return
    let closed = false, retry
    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const base = import.meta.env.VITE_WS_URL || `${proto}://${location.host}/api/ws`
      const ws = new WebSocket(`${base}?token=${useStore.getState().access}`)
      wsRef.current = ws
      ws.onmessage = (m) => {
        try {
          const msg = JSON.parse(m.data)
          if (msg.type === 'notification') { toast(msg.notification.title + ': ' + msg.notification.message); refreshUnread() }
          window.dispatchEvent(new CustomEvent('eh:realtime', { detail: msg }))
        } catch { /* ignore */ }
      }
      ws.onclose = () => { if (!closed) retry = setTimeout(connect, 4000) }
    }
    connect()
    const ping = setInterval(() => wsRef.current?.readyState === 1 && wsRef.current.send('ping'), 25000)
    return () => { closed = true; clearTimeout(retry); clearInterval(ping); wsRef.current?.close() }
  }, [access]) // eslint-disable-line

  const doLogout = async () => {
    try { await api.post('/auth/logout', { refresh_token: useStore.getState().refresh }) } catch { /* ignore */ }
    logout(); nav('/login')
  }

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">EventHub</div>
        <nav>
          {NAV.filter(([, , min]) => can(min) || !orgs.length).map(([to, text]) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'on' : '')}>
              {text}{text === 'Notifications' && unread > 0 && <span className="dot">{unread}</span>}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="main">
        <header className="top">
          <select aria-label="Active organization" value={activeOrgId || ''} onChange={(e) => setActiveOrg(Number(e.target.value))}>
            {!orgs.length && <option value="">No organization</option>}
            {orgs.map((o) => <option key={o.id} value={o.id}>{o.name} ({o.my_role?.replace('_', ' ')})</option>)}
          </select>
          <div className="row">
            <NavLink to="/notifications" className="bell" aria-label="Notifications">🔔{unread > 0 && <span className="dot">{unread}</span>}</NavLink>
            <span className="muted hide-sm">{user?.full_name}</span>
            <button className="btn sm" onClick={doLogout}>Log out</button>
          </div>
        </header>
        <main className="content"><Outlet /></main>
      </div>
      <Toasts />
    </div>
  )
}
