import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api/client'

// 缩略图节流：全局并发 2、结果缓存 30s。
// 一屏 20 张卡时若每张都直接请求截图，会把后端和 adb 打爆，所以统一排队。
const CONCURRENCY = 2
const CACHE_TTL = 30000

const queue = []
const cache = new Map() // deviceId -> { frame, ts }
let active = 0

function pump() {
  while (active < CONCURRENCY && queue.length) {
    const job = queue.shift()
    active += 1
    job().finally(() => {
      active -= 1
      pump()
    })
  }
}

function enqueue(fn) {
  return new Promise((resolve, reject) => {
    queue.push(() => fn().then(resolve, reject))
    pump()
  })
}

async function fetchFrame(deviceId) {
  const hit = cache.get(deviceId)
  if (hit && Date.now() - hit.ts < CACHE_TTL) return hit.frame
  const r = await api.screenshot(deviceId)
  const frame = r.data?.frame || ''
  cache.set(deviceId, { frame, ts: Date.now() })
  return frame
}

/**
 * 设备卡片缩略图：进入可视区后才排队取帧，离开可视区停止轮询。
 * 传入 targetRef（卡片缩略图 DOM）时用 IntersectionObserver 做可视区懒加载；
 * 不传则退回「挂载即加载」的旧行为。失败静默（不打扰用户），保留上一帧。
 */
export function useThumbnail(deviceId, interval = 30000, targetRef = null) {
  const frame = ref('')
  let timer = null
  let stopped = false
  let observer = null

  async function load() {
    try {
      const next = await enqueue(() => fetchFrame(deviceId))
      if (!stopped) frame.value = next
    } catch {
      /* 取帧失败保留旧图 */
    }
  }

  function start() {
    if (timer) return
    load()
    timer = setInterval(load, interval)
  }

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  if (targetRef) {
    onMounted(() => {
      const el = targetRef.value
      if (!el || typeof IntersectionObserver === 'undefined') {
        start()
        return
      }
      observer = new IntersectionObserver(
        (entries) => {
          const visible = entries.some((e) => e.isIntersecting)
          if (visible) start()
          else stop()
        },
        { rootMargin: '100px' },
      )
      observer.observe(el)
    })
  } else {
    start()
  }

  onBeforeUnmount(() => {
    stopped = true
    stop()
    observer?.disconnect()
    observer = null
  })

  return { frame }
}
