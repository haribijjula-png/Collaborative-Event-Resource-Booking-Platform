import { useState } from 'react'
import api, { errMsg } from '../api'
import { useRole, useStore } from '../store'
import { label, rules, useDebounced, useFetch, validate } from '../utils'
import { Badge, Card, Empty, ErrorBox, Field, Modal, Pagination, Spinner } from '../components/ui'

const TYPES = ['meeting_room', 'conference_hall', 'projector', 'camera', 'vehicle', 'equipment']

export default function Resources() {
  const { orgId, can } = useRole(), toast = useStore((s) => s.toast)
  const [page, setPage] = useState(1), [search, setSearch] = useState(''), [type, setType] = useState(''), [status, setStatus] = useState('')
  const q = useDebounced(search), [form, setForm] = useState(null)
  const { data, loading, error, reload } = useFetch(() => orgId ? api.get('/resources', { params: { organization_id: orgId, page, page_size: 10, search: q || undefined, type: type || undefined, status: status || undefined } }).then((r) => r.data.data) : Promise.resolve(null), [orgId, page, q, type, status])
  const admin = can('org_admin')
  const toggle = async (r) => { try { await api.post(`/resources/${r.id}/${r.status === 'active' ? 'deactivate' : 'activate'}`); reload() } catch (e) { toast(errMsg(e), 'error') } }

  const Form = ({ res }) => {
    const [v, setV] = useState({ name: res?.name || '', type: res?.type || 'meeting_room', description: res?.description || '', location: res?.location || '', capacity: res?.capacity || '' })
    const [errors, setErrors] = useState({}), [err, setErr] = useState(null)
    const set = (k) => (e) => setV({ ...v, [k]: e.target.value })
    const save = async () => {
      const e = validate(v, { name: [rules.required, rules.min(2)], capacity: (x) => (x === '' || rules.positiveInt(x) === null ? null : 'Must be a positive number') }); setErrors(e)
      if (Object.keys(e).length) return
      const body = { ...v, capacity: v.capacity ? Number(v.capacity) : null }
      try { res ? await api.patch(`/resources/${res.id}`, body) : await api.post('/resources', { ...body, organization_id: orgId }); toast('Saved', 'success'); setForm(null); reload() } catch (x) { setErr(errMsg(x)) }
    }
    return <Modal title={res ? 'Edit resource' : 'New resource'} onClose={() => setForm(null)} footer={<button className="btn primary" onClick={save}>Save</button>}>
      <ErrorBox error={err} />
      <Field label="Name" error={errors.name}><input value={v.name} onChange={set('name')} /></Field>
      <div className="two"><Field label="Type"><select value={v.type} onChange={set('type')}>{TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}</select></Field>
        <Field label="Capacity" error={errors.capacity}><input type="number" min="1" value={v.capacity} onChange={set('capacity')} /></Field></div>
      <Field label="Location"><input value={v.location} onChange={set('location')} /></Field>
      <Field label="Description"><textarea rows={2} value={v.description} onChange={set('description')} /></Field>
    </Modal>
  }
  if (!orgId) return <Empty title="Select an organization" />
  return (
    <>
      <div className="page-h"><h2>Resources</h2>{admin && <button className="btn primary" onClick={() => setForm({})}>+ New resource</button>}</div>
      <div className="filters"><input placeholder="Search…" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
        <select value={type} onChange={(e) => { setType(e.target.value); setPage(1) }}><option value="">All types</option>{TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}</select>
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}><option value="">Any status</option><option>active</option><option>inactive</option></select></div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No resources" hint={admin ? 'Define rooms and equipment that can be booked.' : undefined} /> : (
        <Card><div className="table-wrap"><table><thead><tr><th>Name</th><th>Type</th><th>Location</th><th>Capacity</th><th>Status</th>{admin && <th />}</tr></thead>
          <tbody>{data.items.map((r) => <tr key={r.id}><td><b>{r.name}</b></td><td>{label(r.type)}</td><td>{r.location || '—'}</td><td>{r.capacity ?? '—'}</td><td><Badge value={r.status} /></td>
            {admin && <td className="row"><button className="btn sm" onClick={() => setForm(r)}>Edit</button><button className="btn sm" onClick={() => toggle(r)}>{r.status === 'active' ? 'Deactivate' : 'Activate'}</button></td>}</tr>)}</tbody></table></div>
          <Pagination data={data} onPage={setPage} /></Card>)}
      {form && <Form res={form.id ? form : null} />}
    </>
  )
}
