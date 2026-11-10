import { useCallback, useEffect, useRef, useState } from 'react'
import { errMsg } from './api'

export const fmt = (d) => (d ? new Date(d).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—')
export const fmtDate = (d) => (d ? new Date(d).toLocaleDateString([], { dateStyle: 'medium' }) : '—')
export const toLocalInput = (d) => {
  if (!d) return ''
  const x = new Date(d)
  x.setMinutes(x.getMinutes() - x.getTimezoneOffset())
  return x.toISOString().slice(0, 16)
}
export const fromLocalInput = (v) => (v ? new Date(v).toISOString() : null)
export const label = (s) => (s || '').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

/** Data-fetching hook with loading / error / reload. */
export function useFetch(fn, deps = []) {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  const seq = useRef(0)
  const run = useCallback(async () => {
    const id = ++seq.current
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await fn()
      if (id === seq.current) setState({ data, loading: false, error: null })
    } catch (e) {
      if (id === seq.current) setState({ data: null, loading: false, error: errMsg(e) })
    }
  }, deps) // eslint-disable-line
  useEffect(() => { run() }, [run])
  return { ...state, reload: run }
}

export function useDebounced(value, ms = 350) {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

// ---- tiny form validators ----
export const rules = {
  required: (v) => (String(v ?? '').trim() ? null : 'Required'),
  email: (v) => (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v || '') ? null : 'Enter a valid email'),
  min: (n) => (v) => ((v || '').length >= n ? null : `At least ${n} characters`),
  password: (v) => (/^(?=.*[A-Za-z])(?=.*\d).{8,}$/.test(v || '') ? null : 'Min 8 chars with a letter and a digit'),
  username: (v) => (/^[A-Za-z0-9_.-]{3,50}$/.test(v || '') ? null : '3-50 chars: letters, digits, _ . -'),
  positiveInt: (v) => (Number.isInteger(Number(v)) && Number(v) > 0 ? null : 'Must be a positive whole number'),
}
export function validate(values, schema) {
  const errors = {}
  for (const [k, fns] of Object.entries(schema)) {
    for (const f of [].concat(fns)) {
      const m = f(values[k], values)
      if (m) { errors[k] = m; break }
    }
  }
  return errors
}
