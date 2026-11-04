import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({ baseURL: '/api', timeout: 60000 })

// 注入 JWT
http.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// 401 自动登出：清 token → 提示 → 回登录页
//
// 坑（曾导致「页面空白、既不提示也不跳登录」）：只删 localStorage 是不够的。
// 路由守卫读的是 Pinia store 里的 token，store 只在创建时从 localStorage 取过一次，
// 删了 localStorage 后 store.isAuthed 仍为 true → 守卫把 /login 又弹回 /devices，
// 于是卡在一个请求全 401 的空页面上。必须同时清掉 store。
let handling401 = false
let last403At = 0
const unreachableToastAt = new Map() // device_id -> 上次提示时刻，节流用
http.interceptors.response.use(
  (r) => r,
  async (err) => {
    const status = err.response?.status
    const url = err.config?.url || ''
    // 登录接口自己返回的 401 是「账号密码错误」，交给登录页提示，别在这里抢话
    if (status === 401 && !url.includes('/auth/login') && !handling401) {
      handling401 = true
      localStorage.removeItem('token')
      try {
        const { useAuth } = await import('../stores/auth')
        useAuth().logout() // 关键：同步清掉 store，否则路由守卫仍认为已登录
      } catch {
        /* pinia 未就绪（极早期请求），localStorage 已清，跳转仍有效 */
      }
      ElMessage.warning('登录状态已失效，请重新登录')
      if (!location.hash.startsWith('#/login')) location.hash = '#/login'
      // 并发请求会一起 401，1 秒内只提示/跳转一次
      setTimeout(() => {
        handling401 = false
      }, 1000)
    }

    // 403：统一可读提示，不把原始错误对象甩给用户；并发请求 1 秒内只提示一次
    if (status === 403) {
      const now = Date.now()
      if (now - last403At > 1000) {
        last403At = now
        const detail = err.response?.data?.detail
        ElMessage.warning(
          detail
            ? `${detail}（当前角色无权限，请联系管理员）`
            : '当前角色无权限，请联系管理员',
        )
      }
    }

    // 503 设备失联：明确告诉用户哪台掉了、怎么救，而不是让页面默默不动。
    // 取帧最高 12fps，同一台设备 10 秒内只提示一次，避免刷屏。
    if (status === 503 && err.response?.data?.unreachable) {
      const d = err.response.data
      const now = Date.now()
      if (now - (unreachableToastAt.get(d.device_id) || 0) > 10000) {
        unreachableToastAt.set(d.device_id, now)
        ElMessage.error({
          message: `设备 ${d.device_id} 已失联，画面与操作均不可用。${d.hint || ''}`,
          duration: 6000,
        })
      }
    }
    return Promise.reject(err)
  },
)

export const api = {
  // 鉴权
  login: (username, password, captcha) =>
    http.post('/auth/login', { username, password, ...(captcha || {}) }),
  captcha: () => http.get('/auth/captcha'),
  me: () => http.get('/auth/me'),

  // 设备
  listDevices: (params) => http.get('/devices', { params }),
  getDevice: (id) => http.get(`/devices/${id}`),
  createDevice: (body) => http.post('/devices', body),
  batchCreate: (body) => http.post('/devices/batch', body),
  listFingerprintPolicies: () => http.get('/devices/fingerprint-policies'),
  updateDevice: (id, body) => http.patch(`/devices/${id}`, body),
  deleteDevice: (id) => http.delete(`/devices/${id}`),
  batchDelete: (ids) => http.post('/devices/batch-delete', { device_ids: ids }),
  banDevice: (id, body) => http.post(`/devices/${id}/ban`, body),
  unbanDevice: (id) => http.post(`/devices/${id}/unban`, {}),
  startDevice: (id) => http.post(`/devices/${id}/start`),
  stopDevice: (id) => http.post(`/devices/${id}/stop`),
  restartDevice: (id) => http.post(`/devices/${id}/restart`),
  renewDevice: (id, body) => http.post(`/devices/${id}/renew`, body),
  batchRenew: (deviceIds, body) => http.post('/devices/batch-renew', { device_ids: deviceIds, ...body }),
  getRenewing: () => http.get('/devices/renewing'),
  claimDevice: (id) => http.post(`/devices/${id}/claim`),
  releaseDevice: (id) => http.post(`/devices/${id}/release`),
  checkDevices: () => http.post('/devices/check', null, { timeout: 180000 }),
  discoverDevices: () => http.get('/devices/discover'),
  adoptDevice: (body) => http.post('/devices/adopt', body),
  listSnapshots: (id) => http.get(`/devices/${id}/snapshots`),
  createSnapshot: (id, name) => http.post(`/devices/${id}/snapshots`, { name }, { timeout: 180000 }),
  restoreSnapshot: (id, sid, confirmName) =>
    http.post(`/devices/${id}/snapshots/${sid}/restore`, { confirm_name: confirmName }, { timeout: 180000 }),
  // 重置两入口（V3）：必须带设备名二次确认，后端同样校验
  restoreLatestSnapshot: (id, confirmName) =>
    http.post(`/devices/${id}/reset/restore-snapshot`, { confirm_name: confirmName }, { timeout: 300000 }),
  wipeDeviceData: (id, confirmName) =>
    http.post(`/devices/${id}/reset/wipe-data`, { confirm_name: confirmName }, { timeout: 300000 }),
  deleteSnapshot: (id, sid) => http.delete(`/devices/${id}/snapshots/${sid}`),
  screenshot: (id, params) => http.get(`/devices/${id}/screenshot`, { params }),
  // 投屏遮罩（V3）：仅本端视觉锁定 + 审计，不是服务端占用
  lockDeviceScreen: (id) => http.post(`/devices/${id}/screen-lock`),
  unlockDevice: (id) => http.post(`/devices/${id}/unlock`),
  // 设备共享（V3，同租户）
  listDeviceShares: (id) => http.get(`/devices/${id}/shares`),
  createDeviceShare: (id, userId) => http.post(`/devices/${id}/shares`, { user_id: userId }),
  revokeDeviceShare: (id, shareId) => http.delete(`/devices/${id}/shares/${shareId}`),
  shareCandidates: (id) => http.get(`/devices/${id}/share-candidates`),
  listExpiring: (withinHours = 24) => http.get('/devices/expiring', { params: { within_hours: withinHours } }),
  // 云盘
  cloudCategories: () => http.get('/cloud-disk/categories'),
  cloudFiles: (params) => http.get('/cloud-disk/files', { params }),
  cloudUpload: (file, category = 'auto', onProgress) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('category', category)
    return http.post('/cloud-disk/files', fd, { onUploadProgress: onProgress })
  },
  cloudDelete: (id) => http.delete(`/cloud-disk/files/${id}`),
  cloudSetPublic: (id, isPublic) => http.patch(`/cloud-disk/files/${id}`, { is_public: isPublic }),
  cloudDownload: (id) => http.get(`/cloud-disk/files/${id}/download`, { responseType: 'blob' }),
  cloudPush: (payload) => http.post('/cloud-disk/push', payload),
  cloudPushJobs: (limit = 20) => http.get('/cloud-disk/push', { params: { limit } }),
  cloudPushStatus: (jobId) => http.get(`/cloud-disk/push/${jobId}`),
  cloudRetryPush: (jobId) => http.post(`/cloud-disk/push/${jobId}/retry`),
  // 下载中心（V2-3）：生成物落云盘，下载复用 cloudDownload
  listDownloads: (params) => http.get('/downloads', { params }),
  createDownload: (body) => http.post('/downloads', body, { timeout: 180000 }),
  deleteDownload: (id) => http.delete(`/downloads/${id}`),
  // IP 资源池
  listIps: (params) => http.get('/ips', { params }),
  createIp: (body) => http.post('/ips', body),
  updateIp: (id, body) => http.patch(`/ips/${id}`, body),
  deleteIp: (id) => http.delete(`/ips/${id}`),
  testIp: (id) => http.post(`/ips/${id}/test`),
  bindIp: (id, body) => http.post(`/ips/${id}/bind`, body),
  unbindIp: (id, body) => http.post(`/ips/${id}/unbind`, body),

  // 分组
  listGroups: () => http.get('/groups'),
  groupTree: () => http.get('/groups/tree'),
  createGroup: (body) => http.post('/groups', body),
  deleteGroup: (id) => http.delete(`/groups/${id}`),
  moveGroupDevices: (id, body) => http.post(`/groups/${id}/move-devices`, body),

  // 皮肤 · 一键换肤
  listSkinThemes: () => http.get('/skin/themes'),
  getSkinApplying: () => http.get('/skin/applying'),
  getSkin: (id, screen, theme) => http.get(`/skin/${id}`, { params: { screen, theme } }),
  applySkin: (id, theme) => http.post(`/skin/${id}`, { theme }),
  applySkinBatch: (deviceIds, theme) => http.post('/skin/batch', { device_ids: deviceIds, theme }),

  // 单机操控
  control: (id, action, body, config) => http.post(`/devices/${id}/control/${action}`, body, config),
  // V5：显示与投屏渲染质量
  setDisplay: (id, width, height, dpi) =>
    http.post(`/devices/${id}/control/display`, { width, height, dpi }, { timeout: 180000 }),
  resetDisplay: (id) =>
    http.post(`/devices/${id}/control/display/reset`, null, { timeout: 180000 }),
  setRenderQuality: (id, quality) =>
    http.post(`/devices/${id}/control/render-quality`, { quality }),

  // 批量
  batch: (action, body) => http.post(`/batch/${action}`, body),

  // 脚本
  listScripts: () => http.get('/scripts'),
  createScript: (body) => http.post('/scripts', body),
  deleteScript: (id) => http.delete(`/scripts/${id}`),
  runScript: (id, deviceIds) => http.post(`/scripts/${id}/run`, { device_ids: deviceIds }),

  // 用户封禁
  banUser: (id, body) => http.post(`/users/${id}/ban`, body),
  unbanUser: (id) => http.post(`/users/${id}/unban`, {}),
}

export default http
