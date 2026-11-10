import axios from 'axios'
import { useStore } from './store'

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || '/api', timeout: 20000 })

api.interceptors.request.use((cfg) => {
  const t = useStore.getState().access
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

let refreshing = null
async function doRefresh() {
  const { refresh, setTokens, logout } = useStore.getState()
  if (!refresh) throw new Error('no refresh token')
  try {
    // plain axios (not `api`) so this call doesn't re-enter the interceptor
    const r = await axios.post((import.meta.env.VITE_API_URL || '/api') + '/auth/refresh', { refresh_token: refresh })
    setTokens(r.data.data.access_token, r.data.data.refresh_token)
    return r.data.data.access_token
  } catch (e) {
    logout()
    throw e
  }
}

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const { response, config } = error
    const code = response?.data?.error?.code
    // Access token expired: refresh once (shared across concurrent requests) then replay.
    if (response?.status === 401 && code === 'TOKEN_EXPIRED' && !config._retried && !config.url.includes('/auth/')) {
      config._retried = true
      refreshing = refreshing || doRefresh().finally(() => (refreshing = null))
      try {
        const token = await refreshing
        config.headers.Authorization = `Bearer ${token}`
        return api(config)
      } catch {
        return Promise.reject(error)
      }
    }
    if (response?.status === 401 && !config.url.includes('/auth/login')) useStore.getState().logout()
    return Promise.reject(error)
  },
)

export function errMsg(e) {
  const err = e?.response?.data?.error
  if (err?.details?.length) return err.details.map((d) => `${d.field}: ${d.message}`).join('; ')
  if (err?.message) return err.message
  if (e?.code === 'ECONNABORTED') return 'Request timed out.'
  if (!e?.response) return 'Cannot reach the server. Check your connection.'
  return 'Something went wrong.'
}
export const errCode = (e) => e?.response?.data?.error?.code

export default api
