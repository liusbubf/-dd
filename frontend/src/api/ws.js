// WebSocket 客户端：订阅预览帧 + 接收设备状态/批量进度广播。
// 自动重连；对外暴露 on(type, handler) 订阅、subscribe(ids, fps) 订阅预览。

export class DeviceSocket {
  constructor() {
    this.ws = null
    this.handlers = {}
    this.sub = { device_ids: [], fps: 1 }
    this._timer = null
  }

  connect() {
    this._gen = (this._gen || 0) + 1
    const gen = this._gen
    if (this.ws) {
      this.ws.onclose = null
      this.ws.onerror = null
      try { this.ws.close() } catch { /* 旧连接已经没了 */ }
    }
    const token = localStorage.getItem('token') || ''
    if (!token) return // 未登录不建立连接，避免无效握手
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const qs = `?token=${encodeURIComponent(token)}`
    const ws = new WebSocket(`${proto}://${location.host}/api/ws${qs}`)
    this.ws = ws
    ws.onopen = () => {
      if (gen !== this._gen) return
      this._send({ type: 'subscribe', ...this.sub })
    }
    ws.onmessage = (ev) => {
      if (gen !== this._gen) return
      let msg
      try {
        msg = JSON.parse(ev.data)
      } catch {
        return
      }
      const hs = this.handlers[msg.type] || []
      hs.forEach((h) => h(msg))
    }
    ws.onclose = () => {
      if (gen !== this._gen) return
      clearTimeout(this._timer)
      if (!localStorage.getItem('token')) return // 已退出登录，不再重连
      this._timer = setTimeout(() => this.connect(), 1500)
    }
  }

  _send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj))
  }

  subscribe(deviceIds, fps = 1) {
    this.sub = { device_ids: deviceIds, fps }
    if (!this.ws || (this.ws.readyState !== WebSocket.OPEN && this.ws.readyState !== WebSocket.CONNECTING)) {
      this.connect()
    }
    this._send({ type: 'subscribe', ...this.sub })
  }

  on(type, handler) {
    ;(this.handlers[type] ||= []).push(handler)
    return () => {
      this.handlers[type] = (this.handlers[type] || []).filter((h) => h !== handler)
    }
  }

  close() {
    if (this.ws) {
      this.ws.onclose = null
      this.ws.close()
    }
    clearTimeout(this._timer)
  }
}

export const socket = new DeviceSocket()
