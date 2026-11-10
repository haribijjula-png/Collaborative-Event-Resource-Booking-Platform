import { create } from 'zustand'

const load = (k, d) => {
  try { return JSON.parse(localStorage.getItem(k)) ?? d } catch { return d }
}

export const useStore = create((set, get) => ({
  user: load('eh_user', null),
  access: localStorage.getItem('eh_access'),
  refresh: localStorage.getItem('eh_refresh'),
  orgs: [],
  activeOrgId: load('eh_org', null),
  theme: localStorage.getItem('eh_theme') || 'light',
  unread: 0,
  toasts: [],

  setAuth: ({ user, access_token, refresh_token }) => {
    localStorage.setItem('eh_user', JSON.stringify(user))
    localStorage.setItem('eh_access', access_token)
    localStorage.setItem('eh_refresh', refresh_token)
    set({ user, access: access_token, refresh: refresh_token })
  },
  setTokens: (access, refresh) => {
    localStorage.setItem('eh_access', access)
    localStorage.setItem('eh_refresh', refresh)
    set({ access, refresh })
  },
  setUser: (user) => { localStorage.setItem('eh_user', JSON.stringify(user)); set({ user }) },
  logout: () => {
    ;['eh_user', 'eh_access', 'eh_refresh'].forEach((k) => localStorage.removeItem(k))
    set({ user: null, access: null, refresh: null, orgs: [], unread: 0 })
  },
  setOrgs: (orgs) => {
    const cur = get().activeOrgId
    const valid = orgs.find((o) => o.id === cur) ? cur : orgs[0]?.id ?? null
    if (valid) localStorage.setItem('eh_org', JSON.stringify(valid))
    set({ orgs, activeOrgId: valid })
  },
  setActiveOrg: (id) => { localStorage.setItem('eh_org', JSON.stringify(id)); set({ activeOrgId: id }) },
  setTheme: (theme) => { localStorage.setItem('eh_theme', theme); set({ theme }) },
  setUnread: (unread) => set({ unread }),
  toast: (message, kind = 'info') => {
    const id = Math.random()
    set((s) => ({ toasts: [...s.toasts, { id, message, kind }] }))
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 4500)
  },
}))

export const RANK = { participant: 1, staff: 2, event_manager: 3, org_admin: 4, super_admin: 4 }
export function useRole() {
  const orgs = useStore((s) => s.orgs)
  const id = useStore((s) => s.activeOrgId)
  const role = orgs.find((o) => o.id === id)?.my_role || null
  return { role, orgId: id, can: (min) => !!role && RANK[role] >= RANK[min] }
}
