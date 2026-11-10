import { useState } from 'react'
import api, { errMsg } from '../api'
import { useRole, useStore } from '../store'
import { fmt, fromLocalInput, useFetch, validate, toLocalInput } from '../utils'
import { Badge, Card, Empty, ErrorBox, Field, Modal, Pagination, Spinner } from '../components/ui'

export default function Bookings() {
  const { orgId, can } = useRole(), { user, toast } = useStore()
  const [f, setF] = useState({ page: 1, resource_id: '', status: '', date_from: '', date_to: '', mine: false })
  const [open, setOpen] = useState(false)
  const resources = useFetch(() => orgId ? api.get('/resources', { params: { organization_id: orgId, page_size: 100 } }).then((r) => r.data.data.items) : Promise.resolve([]), [orgId])
  const { data, loading, error, reload } = useFetch(() => orgId ? api.get('/bookings', { params: { organization_id: orgId, page: f.page, page_size: 10, resource_id: f.resource_id || undefined, status: f.status || undefined,
    requested_by: f.mine ? user.id : undefined, date_from: f.date_from ? new Date(f.date_from).toISOString() : undefined, date_to: f.date_to ? new Date(f.date_to + 'T23:59:59').toISOString() : undefined } }).then((r) => r.data.data) : Promise.resolve(null),
    [orgId, f.page, f.resource_id, f.status, f.date_from, f.date_to, f.mine])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value, page: 1 })
  const act = async (b, a, msg) => { try { await api.post(`/bookings/${b.id}/${a}`); toast(msg, 'success'); reload() } catch (e) { toast(errMsg(e), 'error') } }

  const Form = () => {
    const [v, setV] = useState({ resource_id: '', start_time: '', end_time: '', purpose: '' }), [errors, setErrors] = useState({}), [err, setErr] = useState(null)
    const save = async () => {
      const e = validate(v, { resource_id: (x) => (x ? null : 'Choose a resource'), start_time: (x) => (!x ? 'Required' : new Date(x) < new Date() ? 'Must be in the future' : null),
        end_time: (x, a) => (!x ? 'Required' : new Date(x) <= new Date(a.start_time) ? 'Must be after start' : null) }); setErrors(e)
      if (Object.keys(e).length) return
      try { await api.post('/bookings', { ...v, resource_id: Number(v.resource_id), start_time: fromLocalInput(v.start_time), end_time: fromLocalInput(v.end_time) }); toast('Booking requested', 'success'); setOpen(false); reload() }
      catch (x) { setErr(errMsg(x)) }   // e.g. RESOURCE_ALREADY_BOOKED
    }
    const set2 = (k) => (e) => setV({ ...v, [k]: e.target.value })
    return <Modal title="Request a booking" onClose={() => setOpen(false)} footer={<button className="btn primary" onClick={save}>Request</button>}>
      <ErrorBox error={err} />
      <Field label="Resource" error={errors.resource_id}><select value={v.resource_id} onChange={set2('resource_id')}><option value="">Choose…</option>{resources.data?.filter((r) => r.status === 'active').map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select></Field>
      <div className="two"><Field label="Start" error={errors.start_time}><input type="datetime-local" value={v.start_time} onChange={set2('start_time')} /></Field><Field label="End" error={errors.end_time}><input type="datetime-local" value={v.end_time} onChange={set2('end_time')} /></Field></div>
      <Field label="Purpose"><textarea rows={2} value={v.purpose} onChange={set2('purpose')} /></Field>
    </Modal>
  }
  if (!orgId) return <Empty title="Select an organization" />
  return (
    <>
      <div className="page-h"><h2>Bookings</h2><button className="btn primary" onClick={() => setOpen(true)}>+ Request booking</button></div>
      <div className="filters">
        <select value={f.resource_id} onChange={set('resource_id')}><option value="">All resources</option>{resources.data?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select>
        <select value={f.status} onChange={set('status')}><option value="">Any status</option>{['requested', 'approved', 'rejected', 'cancelled', 'completed'].map((s) => <option key={s}>{s}</option>)}</select>
        <input type="date" aria-label="From" value={f.date_from} onChange={set('date_from')} /><input type="date" aria-label="To" value={f.date_to} onChange={set('date_to')} />
        <label className="check"><input type="checkbox" checked={f.mine} onChange={set('mine')} /> Mine only</label></div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No bookings" /> : <Card><div className="table-wrap"><table>
        <thead><tr><th>Resource</th><th>When</th><th>Purpose</th><th>Status</th><th /></tr></thead>
        <tbody>{data.items.map((b) => <tr key={b.id}><td><b>{b.resource.name}</b></td><td>{fmt(b.start_time)}<br />→ {fmt(b.end_time)}</td><td>{b.purpose || '—'}</td><td><Badge value={b.status} /></td>
          <td className="row">{can('event_manager') && b.status === 'requested' && <><button className="btn sm primary" onClick={() => act(b, 'approve', 'Approved')}>Approve</button><button className="btn sm danger" onClick={() => act(b, 'reject', 'Rejected')}>Reject</button></>}
            {['requested', 'approved'].includes(b.status) && (b.requested_by === user.id || can('event_manager')) && <button className="btn sm" onClick={() => act(b, 'cancel', 'Cancelled')}>Cancel</button>}</td></tr>)}</tbody></table></div>
        <Pagination data={data} onPage={(p) => setF({ ...f, page: p })} /></Card>}
      {open && <Form />}
    </>
  )
}
