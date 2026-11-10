import { useState } from 'react'
import api, { errMsg } from '../api'
import { useRole, useStore } from '../store'
import { rules, useDebounced, useFetch, validate } from '../utils'
import { Badge, Card, Empty, ErrorBox, Field, Modal, Pagination, Spinner } from '../components/ui'

const ROLES = ['org_admin', 'event_manager', 'staff', 'participant']

export default function Members() {
  const { orgId, can } = useRole(), toast = useStore((s) => s.toast)
  const [page, setPage] = useState(1), [search, setSearch] = useState(''), [role, setRole] = useState('')
  const q = useDebounced(search)
  const [open, setOpen] = useState(false)
  const { data, loading, error, reload } = useFetch(() => orgId ? api.get(`/organizations/${orgId}/members`, { params: { page, page_size: 10, search: q || undefined, role: role || undefined } }).then((r) => r.data.data) : Promise.resolve(null), [orgId, page, q, role])
  const admin = can('org_admin')
  const act = async (fn, msg) => { try { await fn(); toast(msg, 'success'); reload() } catch (e) { toast(errMsg(e), 'error') } }
  const base = `/organizations/${orgId}/members`

  const Add = () => {
    const [v, setV] = useState({ email: '', role: 'participant' }), [errors, setErrors] = useState({}), [err, setErr] = useState(null)
    const save = async () => {
      const e = validate(v, { email: rules.email }); setErrors(e); if (Object.keys(e).length) return
      try { await api.post(base, v); toast('Member added', 'success'); setOpen(false); reload() } catch (x) { setErr(errMsg(x)) }
    }
    return <Modal title="Add member" onClose={() => setOpen(false)} footer={<button className="btn primary" onClick={save}>Add</button>}>
      <ErrorBox error={err} />
      <Field label="Email of a registered user" error={errors.email}><input value={v.email} onChange={(e) => setV({ ...v, email: e.target.value })} /></Field>
      <Field label="Role"><select value={v.role} onChange={(e) => setV({ ...v, role: e.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{r.replace('_', ' ')}</option>)}</select></Field>
    </Modal>
  }
  if (!orgId) return <Empty title="Select an organization" />
  return (
    <>
      <div className="page-h"><h2>Members</h2>{admin && <button className="btn primary" onClick={() => setOpen(true)}>+ Add member</button>}</div>
      <div className="filters">
        <input placeholder="Search name, email, username…" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
        <select value={role} onChange={(e) => { setRole(e.target.value); setPage(1) }}><option value="">All roles</option>{ROLES.map((r) => <option key={r} value={r}>{r.replace('_', ' ')}</option>)}</select>
      </div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No members found" /> : (
        <Card><div className="table-wrap"><table>
          <thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Status</th>{admin && <th>Actions</th>}</tr></thead>
          <tbody>{data.items.map((m) => (
            <tr key={m.id}><td>{m.user.full_name}</td><td>@{m.user.username}</td>
              <td>{admin ? <select value={m.role} onChange={(e) => act(() => api.patch(`${base}/${m.id}/role`, { role: e.target.value }), 'Role updated')}>{ROLES.map((r) => <option key={r} value={r}>{r.replace('_', ' ')}</option>)}</select> : <Badge value={m.role} />}</td>
              <td><Badge value={m.is_active ? 'active' : 'inactive'} /></td>
              {admin && <td className="row">
                <button className="btn sm" onClick={() => act(() => api.post(`${base}/${m.id}/${m.is_active ? 'deactivate' : 'activate'}`), m.is_active ? 'Deactivated' : 'Activated')}>{m.is_active ? 'Deactivate' : 'Activate'}</button>
                <button className="btn sm danger" onClick={() => window.confirm(`Remove ${m.user.full_name}?`) && act(() => api.delete(`${base}/${m.id}`), 'Removed')}>Remove</button></td>}
            </tr>))}</tbody></table></div>
          <Pagination data={data} onPage={setPage} /></Card>
      )}
      {open && <Add />}
    </>
  )
}
