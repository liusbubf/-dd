import { defineStore, acceptHMRUpdate } from 'pinia'
import { api } from '../api/client'
import { socket } from '../api/ws'

// 一键新机阶段 → 展示文案（与后端 renew_progress 的 phase 对应）
export const RENEW_PHASE_TEXT = {
  queued: '排队等待',
  stopping: '删除旧容器',
  wiping: '清空设备数据',
  fingerprint: '生成新身份',
  creating: '重建实例',
  booting: '等待开机',
  skin: '恢复桌面皮肤',
  url: '恢复首页',
  done: '新机完成',
  failed: '新机失败',
}

// 真机换肤落地阶段 → 展示文案（与后端 skin_progress 的 phase 对应）
export const SKIN_PHASE_TEXT = {
  queued: '排队等待',
  launcher: '装 iOS 启动器',
  grid: '布置 iOS 桌面',
  wallpaper: '写入壁纸',
  reboot: '重启生效中',
  prefs: '配置主题',
  done: '换肤完成',
  failed: '换肤失败',
}

// 预览帧来源有两条通道，互为兜底：
//  1) WebSocket 推送（快，但在部分本机代理 / 企业代理下 localhost 的 WS 会被劫持）
//  2) HTTP 轮询 /devices/{id}/screenshot（稳，走 axios + vite 代理，一定通）
// 当近 2.5s 内收到过 WS 帧，则认为 WS 健康，自动跳过 HTTP 轮询，避免重复请求。
let pollTimer = null

export const useDevices = defineStore('devices', {
  state: () => ({
    list: [],
    groups: [],
    frames: {}, // device_id -> data URL 预览帧
    batchProgress: null, // {action, done, total}
    skinProgress: {}, // device_id -> {phase, theme} 真机换肤落地进度（含重启）
    renewProgress: {}, // device_id -> {phase, mode} 一键新机进度
    wsReady: false,
    lastWsFrameAt: 0, // 最近一次经 WS 收到预览帧的时间戳（ms）
    previewIds: [], // 当前正在预览的设备
  }),
  getters: {
    running: (s) => s.list.filter((d) => d.status === 'running'),
    byId: (s) => (id) => s.list.find((d) => d.id === id),
  },
  actions: {
    async refresh(params) {
      const { data } = await api.listDevices(params)
      this.list = data
    },
    async refreshGroups() {
      const { data } = await api.listGroups()
      this.groups = data
    },
    upsert(device) {
      const i = this.list.findIndex((d) => d.id === device.id)
      if (i >= 0) this.list[i] = device
      else this.list.push(device)
    },
    remove(id) {
      this.list = this.list.filter((d) => d.id !== id)
    },
    initSocket() {
      if (this.wsReady) return
      socket.connect()
      socket.on('device_status', (m) => this.upsert(m.device))
      socket.on('device_removed', (m) => this.remove(m.device_id))
      socket.on('preview', (m) => {
        this.lastWsFrameAt = Date.now()
        this.frames[m.device_id] = m.frame
      })
      socket.on('batch_progress', (m) => {
        this.batchProgress = m
      })
      socket.on('skin_progress', (m) => this._onSkinProgress(m))
      socket.on('renew_progress', (m) => this._onRenewProgress(m))
      this.wsReady = true
    },
    _onRenewProgress(m) {
      this.renewProgress[m.device_id] = { phase: m.phase, mode: m.mode }
      if (m.phase === 'done' || m.phase === 'failed') {
        setTimeout(() => {
          if (this.renewProgress[m.device_id]?.phase === m.phase) delete this.renewProgress[m.device_id]
        }, 6000)
      }
    },
    // 页面加载时补齐「正在新机」的设备（增量更新走 WS）
    async refreshRenewing() {
      try {
        const { data } = await api.getRenewing()
        const next = {}
        for (const it of data.renewing || []) next[it.device_id] = { phase: it.phase, mode: it.mode }
        // 保留本端刚收到的终态 6s 提示；其余不在服务端队列里的非终态一律清掉，避免卡在旧阶段
        for (const [id, p] of Object.entries(this.renewProgress)) {
          if (p.phase === 'done' || p.phase === 'failed') next[id] = p
        }
        this.renewProgress = next
      } catch {
        /* 忽略：仅影响进度展示 */
      }
    },
    _onSkinProgress(m) {
      this.skinProgress[m.device_id] = { phase: m.phase, theme: m.theme }
      // 终态（完成/失败）展示 6s 后自动消失
      if (m.phase === 'done' || m.phase === 'failed') {
        setTimeout(() => {
          if (this.skinProgress[m.device_id]?.phase === m.phase) delete this.skinProgress[m.device_id]
        }, 6000)
      }
    },
    // 页面加载时补齐「正在换肤」的设备状态（增量更新走 WS）
    async refreshSkinApplying() {
      try {
        const { data } = await api.getSkinApplying()
        const map = {}
        for (const it of data.applying || []) map[it.device_id] = { phase: it.phase, theme: it.theme }
        this.skinProgress = { ...map, ...this.skinProgress }
      } catch {
        /* 忽略：仅影响进度展示 */
      }
    },
    // 订阅预览：同时尝试 WS 推送 + HTTP 轮询。ids 为空则停止预览。
    // 单机/少量设备（≤3，如单机操控页）：直接高频 HTTP 轮询保证实时，不被 WS 抑制
    //   —— 后端 /screenshot 实测 ~64ms，可稳跑数 fps。
    // 多设备（网格）：WS 优先，HTTP 仅在 WS 不健康时兜底，避免同时打太多请求。
    subscribePreviews(ids, fps = 1) {
      socket.subscribe(ids, fps)
      this.previewIds = ids || []
      if (pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
      }
      if (!this.previewIds.length) return

      // 下限 80ms → 单机「高清投屏」可到 ~10-12fps（后端 /screenshot ~64ms 能跟上）
      const interval = Math.max(80, Math.round(1000 / fps))
      const force = this.previewIds.length <= 3
      let busy = false
      const tick = async () => {
        if (busy) return
        if (!force && Date.now() - this.lastWsFrameAt < 2500) return
        busy = true
        try {
          await Promise.allSettled(
            this.previewIds.map(async (id) => {
              const { data } = await api.screenshot(id)
              this.frames[id] = data.frame
            }),
          )
        } finally {
          busy = false
        }
      }
      tick()
      pollTimer = setInterval(tick, interval)
    },
  },
})

// 让本 store 支持热更新，避免开发时编辑 store 导致运行中页面状态损坏、子路由白屏
if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useDevices, import.meta.hot))
}
