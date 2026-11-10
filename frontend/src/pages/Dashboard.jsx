import { Link } from 'react-router-dom'
import api from '../api'
import { useRole } from '../store'
import { fmt, label, useFetch } from '../utils'
import { BarChart, Card, Empty, ErrorBox, Spinner, Badge } from '../components/ui'

export default function Dashboard() {
  const { orgId } = useRole()
  const { data, loading, error, reload } = useFetch(
    () => (orgId ? api.get('/dashboard', { params: { organization_id: orgId } }).then((r) => r.data.data) : Promise.resolve(null)), [orgId])

  if (!orgId) return <Empty title="Welcome to EventHub" hint="Create an organization, or ask an admin to add you to one." />
  if (loading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (!data) return null
  return (
    <>
      <h2>Dashboard <small className="muted">· {label(data.role)}</small></h2>
      <div className="stats">
        {Object.entries(data.cards).map(([k, v]) => (
          <div className="stat" key={k}><div className="stat-v">{k === 'attendance_rate' ? `${v}%` : v}</div><div className="muted">{label(k)}</div></div>
        ))}
      </div>
      <div className="grid2">
        {data.charts && <>
          <Card title="Events by status"><BarChart data={data.charts.events_by_status} title="Events by status" /></Card>
          <Card title="Registrations by status"><BarChart data={data.charts.registrations_by_status} title="Registrations by status" /></Card>
        </>}
        {data.todays_sessions && (
          <Card title="Today's sessions">
            {data.todays_sessions.length ? <ul className="list">{data.todays_sessions.map((s) => <li key={s.id}><b>{s.title}</b><span className="muted">{fmt(s.start_time)} {s.room && `· ${s.room}`}</span></li>)}</ul> : <Empty title="No sessions today" />}
          </Card>
        )}
        {data.upcoming_tasks && (
          <Card title="Upcoming tasks" actions={<Link to="/registrations?status=pending">Review</Link>}>
            {data.upcoming_tasks.length ? <ul className="list">{data.upcoming_tasks.map((t) => <li key={t.registration_id}>Approve registration #{t.registration_id} <Link to={`/events/${t.event_id}`}>event #{t.event_id}</Link></li>)}</ul> : <Empty title="All caught up" />}
          </Card>
        )}
        {data.attendance_history && (
          <Card title="Attendance history">
            {data.attendance_history.length ? <ul className="list">{data.attendance_history.map((a, i) => <li key={i}><Link to={`/events/${a.event_id}`}>Event #{a.event_id}</Link><Badge value={a.status} /></li>)}</ul> : <Empty title="No attendance yet" />}
          </Card>
        )}
        <Card title="Upcoming events" actions={<Link to="/calendar">Calendar</Link>}>
          {data.upcoming?.length ? <ul className="list">{data.upcoming.map((e) => <li key={e.id}><Link to={`/events/${e.id}`}>{e.name}</Link><span className="muted">{fmt(e.start_time)}</span></li>)}</ul> : <Empty title="No upcoming events" />}
        </Card>
      </div>
    </>
  )
}
