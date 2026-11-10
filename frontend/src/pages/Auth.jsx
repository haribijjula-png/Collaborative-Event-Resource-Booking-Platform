import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import api, { errMsg } from '../api'
import { useStore } from '../store'
import { rules, validate } from '../utils'
import { ErrorBox, Field } from '../components/ui'

export function Login() {
  const { setAuth, access } = useStore()
  const nav = useNavigate(), loc = useLocation()
  const [v, setV] = useState({ email: '', password: '' })
  const [errors, setErrors] = useState({}), [error, setError] = useState(null), [busy, setBusy] = useState(false)
  if (access) return <Navigate to="/" replace />
  const submit = async (e) => {
    e.preventDefault()
    const errs = validate(v, { email: rules.email, password: rules.required })
    setErrors(errs); setError(null)
    if (Object.keys(errs).length) return
    setBusy(true)
    try { const r = await api.post('/auth/login', v); setAuth(r.data.data); nav(loc.state?.from || '/', { replace: true }) }
    catch (e2) { setError(errMsg(e2)) } finally { setBusy(false) }
  }
  return (
    <div className="auth"><form className="card auth-card" onSubmit={submit} noValidate>
      <h2>Sign in</h2><ErrorBox error={error} />
      <Field label="Email" error={errors.email}><input type="email" autoComplete="email" value={v.email} onChange={(e) => setV({ ...v, email: e.target.value })} /></Field>
      <Field label="Password" error={errors.password}><input type="password" autoComplete="current-password" value={v.password} onChange={(e) => setV({ ...v, password: e.target.value })} /></Field>
      <button className="btn primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      <p className="muted">No account? <Link to="/register">Register</Link></p>
    </form></div>
  )
}

export function Register() {
  const nav = useNavigate(), toast = useStore((s) => s.toast)
  const [v, setV] = useState({ full_name: '', username: '', email: '', password: '', confirm: '' })
  const [errors, setErrors] = useState({}), [error, setError] = useState(null), [busy, setBusy] = useState(false)
  const set = (k) => (e) => setV({ ...v, [k]: e.target.value })
  const submit = async (e) => {
    e.preventDefault()
    const errs = validate(v, {
      full_name: rules.required, username: rules.username, email: rules.email, password: rules.password,
      confirm: (x, all) => (x === all.password ? null : 'Passwords do not match'),
    })
    setErrors(errs); setError(null)
    if (Object.keys(errs).length) return
    setBusy(true)
    try {
      const { confirm, ...body } = v
      await api.post('/auth/register', body)
      toast('Account created. Please sign in.', 'success'); nav('/login')
    } catch (e2) { setError(errMsg(e2)) } finally { setBusy(false) }
  }
  return (
    <div className="auth"><form className="card auth-card" onSubmit={submit} noValidate>
      <h2>Create account</h2><ErrorBox error={error} />
      <Field label="Full name" error={errors.full_name}><input value={v.full_name} onChange={set('full_name')} /></Field>
      <Field label="Username" error={errors.username} hint="Used for @mentions"><input value={v.username} onChange={set('username')} /></Field>
      <Field label="Email" error={errors.email}><input type="email" value={v.email} onChange={set('email')} /></Field>
      <Field label="Password" error={errors.password}><input type="password" autoComplete="new-password" value={v.password} onChange={set('password')} /></Field>
      <Field label="Confirm password" error={errors.confirm}><input type="password" autoComplete="new-password" value={v.confirm} onChange={set('confirm')} /></Field>
      <button className="btn primary" disabled={busy}>{busy ? 'Creating…' : 'Register'}</button>
      <p className="muted">Already registered? <Link to="/login">Sign in</Link></p>
    </form></div>
  )
}
