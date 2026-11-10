import { useState } from 'react'
import api, { errMsg } from '../api'
import { useStore } from '../store'
import { fmtDate, rules, useFetch, validate } from '../utils'
import { Card, Empty, ErrorBox, Field, Modal, Spinner } from '../components/ui'

export default function Organizations() {
  const { orgs, setOrgs, setActiveOrg, activeOrgId, toast } = useStore()
  const [open, setOpen] = useState(false), [edit, setEdit] = useState(null)
  const { loading, error, reload } = useFetch(() => api.get('/organizations').then((r) => setOrgs(r.data.data)), [])
  const OrgForm = ({ org }) => {
    const [v, setV] = useState({ name: org?.name || '', description: org?.description || '' })
    const [errors, setErrors] = useState({}), [err, setErr] = useState(null)
    const save = async () => {
      const e = validate(v, { name: [rules.required, rules.min(2)] }); setErrors(e)
      if (Object.keys(e).length) return
      try {
        if (org) await api.patch(`/organizations/${org.id}`, v); else { const r = await api.post('/organizations', v); setActiveOrg(r.data.data.id) }
        toast('Saved', 'success'); setOpen(false); setEdit(null); reload()
      } catch (x) { setErr(errMsg(x)) }
    }
    return (
      <Modal title={org ? 'Edit organization' : 'New organization'} onClose={() => { setOpen(false); setEdit(null) }} footer={<button className="btn primary" onClick={save}>Save</button>}>
        <ErrorBox error={err} />
        <Field label="Name" error={errors.name}><input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} /></Field>
        <Field label="Description"><textarea rows={3} value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} /></Field>
      </Modal>
    )
  }
  return (
    <>
      <div className="page-h"><h2>Organizations</h2><button className="btn primary" onClick={() => setOpen(true)}>+ New organization</button></div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !orgs.length ? <Spinner /> : !orgs.length ? <Empty title="No organizations" hint="Create one to start managing events." /> : (
        <div className="grid2">{orgs.map((o) => (
          <Card key={o.id} title={o.name} actions={<>
            {o.my_role === 'org_admin' || o.my_role === 'super_admin' ? <button className="btn sm" onClick={() => setEdit(o)}>Edit</button> : null}
            <button className="btn sm" disabled={o.id === activeOrgId} onClick={() => setActiveOrg(o.id)}>{o.id === activeOrgId ? 'Active' : 'Switch'}</button></>}>
            <p>{o.description || <span className="muted">No description</span>}</p>
            <p className="muted">Your role: {o.my_role?.replace('_', ' ')} · created {fmtDate(o.created_at)}</p>
          </Card>))}</div>
      )}
      {open && <OrgForm />}{edit && <OrgForm org={edit} />}
    </>
  )
}
