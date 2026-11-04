import { defineStore, acceptHMRUpdate } from 'pinia'
import { api } from '../api/client'

// 角色等级与后端 rbac.py 保持一致（低 → 高）
export const ROLE_LEVELS = { viewer: 1, operator: 2, admin: 3, superadmin: 4 }

export const useAuth = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    user: null,
  }),
  getters: {
    isAuthed: (s) => !!s.token,
    role: (s) => s.user?.role || '',
    level: (s) => ROLE_LEVELS[s.user?.role] || 0,
    isAdmin: (s) => (ROLE_LEVELS[s.user?.role] || 0) >= ROLE_LEVELS.admin,
    // 用法：v-if="auth.can('operator')" / :disabled="!auth.can('admin')"
    can: (s) => (minRole = 'operator') =>
      (ROLE_LEVELS[s.user?.role] || 0) >= (ROLE_LEVELS[minRole] || 99),
  },
  actions: {
    async login(username, password, captcha) {
      const { data } = await api.login(username, password, captcha)
      this.token = data.access_token
      this.user = data.user
      localStorage.setItem('token', data.access_token)
      return data
    },
    async fetchMe() {
      const { data } = await api.me()
      this.user = data
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('token')
    },
  },
})

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useAuth, import.meta.hot))
}
