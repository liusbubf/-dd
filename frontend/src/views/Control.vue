<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api/client'
import { useDevices } from '../stores/devices'
import { useAuth } from '../stores/auth'
import ScrcpyPlayer from '../components/ScrcpyPlayer.vue'

const route = useRoute()
const router = useRouter()
const store = useDevices()
const auth = useAuth()
const id = computed(() => Number(route.params.id))
const device = computed(() => store.byId(id.value))
const url = ref('')

// ===== 投屏遮罩（V3）=====
// 本端视觉锁定 + 禁止本端发起控制指令；不做服务端占用态。
// 状态只保存在本端 localStorage，锁定/解锁仅向后端写审计。
const lockInfo = ref(null) // { by, at }
const lockBusy = ref(false)
const locked = computed(() => !!lockInfo.value)
const lockKey = computed(() => `cloud-phone:screen-lock:${id.value}`)

function readLocalLock() {
  lockInfo.value = null
  try {
    const raw = localStorage.getItem(lockKey.value)
    if (raw) lockInfo.value = JSON.parse(raw)
  } catch {
    lockInfo.value = null
  }
}

function fmtLockTime(t) {
  if (!t) return '—'
  const d = new Date(t)
  return Number.isNaN(d.getTime()) ? t : d.toLocaleString()
}

async function lockScreen() {
  if (lockBusy.value || locked.value) return
  lockBusy.value = true
  try {
    await api.lockDeviceScreen(id.value)
    const info = { by: auth.user?.username || '当前用户', at: new Date().toISOString() }
    lockInfo.value = info
    localStorage.setItem(lockKey.value, JSON.stringify(info))
    kbTextarea?.blur()
    ElMessage.success('已锁定本端投屏画面')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '锁定失败')
  } finally {
    lockBusy.value = false
  }
}

async function unlockScreen() {
  if (lockBusy.value) return
  lockBusy.value = true
  try {
    await api.unlockDevice(id.value)
    lockInfo.value = null
    localStorage.removeItem(lockKey.value)
    ElMessage.success('已解除本端投屏遮罩（不涉及服务端占用）')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '解除遮罩失败')
  } finally {
    lockBusy.value = false
  }
}

// ===== 侧边控制按键 =====
const keyBusy = ref(false)
const keyButtons = [
  { key: 'power',       icon: '⏻', label: '电源' },
  { key: 'volume_up',   icon: '🔊', label: '音量+' },
  { key: 'volume_down', icon: '🔉', label: '音量-' },
  { key: 'back',        icon: '◀',  label: '返回' },
  { key: 'home',        icon: '●',  label: '主页' },
  { key: 'recent',      icon: '▣',  label: '任务' },
]
async function sendKey(k) {
  if (keyBusy.value || locked.value) return
  keyBusy.value = true
  try { await api.control(id.value, 'key', { key: k }) } catch { /* 静默 */ }
  finally { keyBusy.value = false }
}

// ===== 键盘直连：电脑键盘 → 云手机中英文输入 =====
const isComposing = ref(false)      // IME 组合输入中
let kbTextarea = null               // 隐藏 textarea，仅用于 IME 组合输入，对用户完全透明
let focusGuardTimer = null          // iframe 抢焦兜底

function ensureKbTextarea() {
  if (kbTextarea) return
  kbTextarea = document.createElement('textarea')
  kbTextarea.style.cssText = 'position:fixed;left:0;top:0;width:1px;height:1px;opacity:0;border:none;outline:none;resize:none;pointer-events:none'
  kbTextarea.setAttribute('autocomplete', 'off')
  document.body.appendChild(kbTextarea)
  kbTextarea.addEventListener('compositionstart', () => { isComposing.value = true })
  kbTextarea.addEventListener('compositionend', (e) => {
    isComposing.value = false
    const text = e.data || kbTextarea.value
    if (text && !locked.value) {
      api.control(id.value, 'text', { text })
      rec('text', { text })
    }
    kbTextarea.value = ''
  })
  kbTextarea.addEventListener('input', (e) => {
    if (isComposing.value || locked.value) return
    const text = e.target.value
    if (text) {
      console.log('[kb] textarea input:', JSON.stringify(text))
      api.control(id.value, 'text', { text })
      rec('text', { text })
    }
    e.target.value = ''
  })
  kbTextarea.focus({ preventScroll: true })
  document.addEventListener('focusin', onDocFocusIn)
  startFocusGuard()
}

function onDocFocusIn() {
  if (!kbTextarea || document.activeElement === kbTextarea) return
  const ae = document.activeElement
  if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.tagName === 'SELECT' || ae.closest?.('.el-select') || ae.closest?.('.el-dialog') || ae.closest?.('.el-popover'))) {
    return
  }
  kbTextarea.focus({ preventScroll: true })
}

// 微任务抢焦：mousedown 捕获阶段用 microtask 抢回焦点，抢在用户按键之前
function onDocMouseDownCapture(e) {
  if (e.target.tagName === 'IFRAME') {
    // microtask 在本次事件完成后、下次用户输入前执行，窗口为 0
    queueMicrotask(() => {
      ensureKbTextarea()
      kbTextarea?.focus({ preventScroll: true })
    })
  }
}

function startFocusGuard() {
  document.addEventListener('mousedown', onDocMouseDownCapture, true)
  if (focusGuardTimer) return
  focusGuardTimer = setInterval(() => {
    if (document.activeElement?.tagName === 'IFRAME') {
      kbTextarea?.focus({ preventScroll: true })
    }
  }, 200)
}

function stopFocusGuard() {
  document.removeEventListener('mousedown', onDocMouseDownCapture, true)
  document.removeEventListener('focusin', onDocFocusIn)
  if (focusGuardTimer) {
    clearInterval(focusGuardTimer)
    focusGuardTimer = null
  }
}

// 全局 keydown：直接操控云手机（不经过任何可见文本框）
function onGlobalKeydown(e) {
  // 调试：记录所有键盘事件
  console.log('[kb] keydown:', e.key, 'code:', e.code, 'shift:', e.shiftKey, 'composing:', e.isComposing, 'len:', e.key.length)
  // 忽略页面 UI 控件中的输入
  const t = e.target
  if (!t) return
  if (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.closest?.('.el-select') || t.closest?.('.el-dialog') || t.closest?.('.el-popover')) {
    if (t !== kbTextarea) return
  }
  if (locked.value) return
  if (e.isComposing || isComposing.value) return
  // 方向键 → 移动光标
  const navKeys = {
    ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down',
    Home: 'move_home', End: 'move_end',
    PageUp: 'page_up', PageDown: 'page_down',
    Tab: 'tab',
  }
  if (navKeys[e.key]) {
    e.preventDefault()
    api.control(id.value, 'key', { key: navKeys[e.key] })
    return
  }
  // 特殊键
  if (e.key === 'Backspace') {
    e.preventDefault()
    api.control(id.value, 'key', { key: 'del' })
    return
  }
  if (e.key === 'Delete') {
    e.preventDefault()
    api.control(id.value, 'key', { key: 'forward_del' })
    return
  }
  if (e.key === 'Enter') {
    e.preventDefault()
    api.control(id.value, 'key', { key: 'enter' })
    return
  }
  if (e.key === 'Escape') {
    e.preventDefault()
    api.control(id.value, 'key', { key: 'back' })
    return
  }
  // Ctrl 快捷键
  if (e.ctrlKey && !e.metaKey && !e.altKey) {
    const ctrlKeys = { a: 'select_all', c: 'copy', x: 'cut', v: 'paste' }
    if (ctrlKeys[e.key]) {
      e.preventDefault()
      api.control(id.value, 'key', { key: ctrlKeys[e.key] })
      return
    }
  }
  // 可打印字符：e.key 已包含 Shift 组合结果（如 Shift+1 → '!'），直接发送
  // 不再依赖隐藏 textarea 的焦点，避免 iframe 抢焦导致键盘完全失效
  if (e.key && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault()
    console.log('[kb] direct key:', JSON.stringify(e.key))
    api.control(id.value, 'text', { text: e.key })
    rec('text', { text: e.key })
    return
  }
}

// 点击/触摸手机画面时确保键盘就绪
function onPhoneInteract() {
  if (locked.value) return
  ensureKbTextarea()
  kbTextarea?.focus({ preventScroll: true })
}

// 脚本录制
const recording = ref(false)
const steps = ref([])
function rec(action, params) {
  if (recording.value) steps.value.push({ action, params })
}

// ===== scrcpy 实时投屏嵌入页面（替代 PhoneFrame 截图预览） =====
const scrcpyOpen = ref(false)
const scrcpyReady = ref(false)
const streamLoading = ref(false)
const streamError = ref('')
const streamInfo = ref(null)
const streamKey = ref(0)
const iframeReady = ref(false)
// 当前已显示的视频流比例（仅在 iframe 加载完成后更新，避免分辨率切换时画面跳动）
const displayRatio = ref('720 / 1280')

const deviceRatio = computed(() => {
  const w = device.value?.width || 720
  const h = device.value?.height || 1280
  return `${w} / ${h}`
})

const streamSrc = computed(() => streamInfo.value?.iframe_url || '')

async function prepareStream(keepOld = false) {
  streamLoading.value = true
  streamError.value = ''
  if (!keepOld) {
    streamInfo.value = null
    iframeReady.value = false
  }
  const oldInfo = streamInfo.value
  try {
    const { data } = await api.control(id.value, 'scrcpy', { action: 'prepare' }, { timeout: 15000 })
    if (!data.ok) { streamError.value = '后端返回失败'; return }
    if (!data.ready) { streamError.value = 'ws-scrcpy 服务未就绪或设备不可达'; return }
    streamInfo.value = data
    scrcpyReady.value = true
  } catch (e) {
    streamError.value = e.message || '请求失败'
    // 如果保留旧流但新流加载失败，恢复旧流
    if (keepOld && oldInfo) streamInfo.value = oldInfo
  } finally {
    streamLoading.value = false
  }
}

async function checkScrcpy() {
  try {
    const { data } = await api.control(id.value, 'scrcpy', { action: 'health' }, { timeout: 5000 })
    scrcpyReady.value = !!data?.ready
  } catch {
    scrcpyReady.value = false
  }
}
function openScrcpy() {
  scrcpyOpen.value = true
}

function onStreamIframeLoad() {
  iframeReady.value = true
  // iframe 加载完成后，将显示比例更新为当前设备分辨率
  displayRatio.value = deviceRatio.value
  // 确保键盘就绪
  onPhoneInteract()
}
function retryStream() { streamKey.value++; prepareStream() }

watch(id, () => {
  streamKey.value++
  readLocalLock()
  prepareStream()
})

onMounted(async () => {
  if (!device.value) await store.refresh()
  url.value = device.value?.current_url || ''
  readLocalLock()
  prepareStream()
  checkScrcpy()
  window.addEventListener('keydown', onGlobalKeydown)
  ensureKbTextarea()
})
onBeforeUnmount(() => {
  store.subscribePreviews([], 1)
  window.removeEventListener('keydown', onGlobalKeydown)
  stopFocusGuard()
  if (kbTextarea) { kbTextarea.remove(); kbTextarea = null }
})

// 操控事件全部 fire-and-forget（不去 await），降低 tap/swipe/键盘/文本的操控延迟
function openUrl() {
  if (locked.value) return ElMessage.warning('画面已锁定，请先解除遮罩')
  api.control(id.value, 'open_url', { url: url.value })
  rec('open_url', { url: url.value })
  ElMessage.success('已打开网页')
}
function key(k) {
  if (locked.value) return
  api.control(id.value, 'key', { key: k })
  rec('key', { key: k })
  if (k === 'home') recentMode.value = false
}

// 最近任务滑删
const recentMode = ref(false)
function openRecent() {
  recentMode.value = true
  key('recent')
}
function onPageClick(e) {
  if (!recentMode.value || locked.value) return
  const t = e.target
  if (
    t.closest('iframe') ||
    t.closest('button') ||
    t.closest('input') ||
    t.closest('textarea') ||
    t.closest('.el-select') ||
    t.closest('.el-switch') ||
    t.closest('.el-card')
  )
    return
  api.control(id.value, 'key', { key: 'back' })
  rec('key', { key: 'back' })
  recentMode.value = false
}

// V5：分辨率/DPI 运行时切换 + 投屏渲染质量
const displayPresets = [
  { label: '720 × 1280 @320', width: 720, height: 1280, dpi: 320 },
  { label: '1080 × 1920 @480', width: 1080, height: 1920, dpi: 480 },
  { label: '1440 × 2560 @560', width: 1440, height: 2560, dpi: 560 },
]
const displaySel = ref(1)
const applying = ref(false)
const resetting = ref(false)
// 自定义分辨率（非 16:9 允许，但后端有总像素与宽高比上限，超限返回 422）
const customOpen = ref(false)
const customW = ref(1080)
const customH = ref(1920)
const customD = ref(480)
const QUALITY_OPTIONS = [
  { label: '低（15fps / 2Mbps）', value: 'low' },
  { label: '中（30fps / 8Mbps）', value: 'medium' },
  { label: '高（60fps / 20Mbps）', value: 'high' },
]
const quality = ref('medium')
const qualityBusy = ref(false)

watch(
  device,
  (d) => {
    if (!d) return
    if (d.render_quality) quality.value = d.render_quality
  },
  { immediate: true }
)

function pickPreset(i) {
  const p = displayPresets[i]
  if (!p) return
  customOpen.value = false
  customW.value = p.width
  customH.value = p.height
  customD.value = p.dpi
}

async function doDisplayChange(width, height, dpi) {
  applying.value = true
  const msg = ElMessage({
    message: `正在切换到 ${width}×${height} @${dpi}dpi，部分后端需重建容器（约 10–30s）…`,
    type: 'info',
    duration: 0,
  })
  try {
    const { data } = await api.setDisplay(id.value, width, height, dpi)
    msg.close()
    await store.refresh()
    if (data?.restart_required) {
      ElMessage.warning('已提交切换，该后端需要重建容器/重启才能生效（约 10–30s）')
    } else {
      ElMessage.success(`已切换为 ${data.width}×${data.height} @${data.dpi}dpi`)
    }
    // 分辨率变了，重建流（先加载新流，再切换 iframe，避免旧流闪烁）
    await prepareStream()
    streamKey.value++
  } catch (e) {
    msg.close()
    const detail = e?.response?.data?.detail
    ElMessage.error(`分辨率切换失败：${detail || e.message || e}`)
  } finally {
    applying.value = false
  }
}

async function applyDisplay() {
  if (locked.value) return ElMessage.warning('画面已锁定，请先解除遮罩')
  if (customOpen.value) return doDisplayChange(Number(customW.value), Number(customH.value), Number(customD.value))
  const p = displayPresets[displaySel.value]
  if (!p) return
  return doDisplayChange(p.width, p.height, p.dpi)
}

async function applyResetDisplay() {
  if (locked.value) return ElMessage.warning('画面已锁定，请先解除遮罩')
  resetting.value = true
  try {
    const { data } = await api.resetDisplay(id.value)
    await store.refresh()
    ElMessage.success(`已恢复原始分辨率 ${data.width}×${data.height} @${data.dpi}dpi`)
    await prepareStream()
    streamKey.value++
  } catch (e) {
    ElMessage.error(`恢复原始分辨率失败：${e?.response?.data?.detail || e.message || e}`)
  } finally {
    resetting.value = false
  }
}

async function changeQuality(q) {
  if (q === quality.value) return
  qualityBusy.value = true
  try {
    await api.setRenderQuality(id.value, q)
    quality.value = q
    await store.refresh()
    ElMessage.success('已切换投屏渲染质量，正在重连视频流…')
    await prepareStream()
    streamKey.value++
  } catch (e) {
    ElMessage.error(`渲染质量切换失败：${e?.response?.data?.detail || e.message || e}`)
  } finally {
    qualityBusy.value = false
  }
}
function swipe(dir) {
  if (locked.value) return
  const w = device.value.width, h = device.value.height
  const p =
    dir === 'up'
      ? { x1: w / 2, y1: h * 0.8, x2: w / 2, y2: h * 0.3, duration_ms: 300 }
      : { x1: w / 2, y1: h * 0.3, x2: w / 2, y2: h * 0.8, duration_ms: 300 }
  api.control(id.value, 'swipe', p)
  rec('swipe', p)
}
async function saveScript() {
  if (!steps.value.length) return ElMessage.warning('还没有录到操作')
  const { value } = await ElMessageBox.prompt('脚本名称', '保存脚本', { inputValue: '开网页脚本' })
  await api.createScript({ name: value, steps: steps.value })
  ElMessage.success(`已保存 ${steps.value.length} 步，去「脚本回放」跨设备执行`)
  steps.value = []
  recording.value = false
}
</script>

<template>
  <div class="page" v-if="device" @click="onPageClick">
    <!-- 顶部工具栏 -->
    <header class="topbar">
      <div class="topbar-left">
        <button class="back-btn" @click="router.push(route.query.from === 'grid' ? '/grid' : '/devices')">
          <span class="back-arrow">←</span>
        </button>
        <div class="device-info">
          <span class="device-name">{{ device.name }}</span>
          <span class="device-meta">
            <em>{{ device.fingerprint?.device?.model }}</em>
            <i class="sep-dot"></i>
            <em class="ip">{{ device.fingerprint?.network?.exit_ip }}</em>
          </span>
        </div>
      </div>
      <div class="topbar-right">
        <button
          v-if="auth.can('operator')"
          class="action-btn lock"
          :class="{ on: locked }"
          :disabled="lockBusy"
          @click="locked ? unlockScreen() : lockScreen()"
        >
          <span class="btn-icon">{{ locked ? '🔓' : '🔒' }}</span>
          <span>{{ locked ? '解除遮罩' : '锁定画面' }}</span>
        </button>
        <button v-if="auth.can('operator')" class="action-btn popout" @click="openScrcpy">
          <span class="btn-icon">⛶</span>
          <span>弹出投屏</span>
        </button>
        <label v-if="auth.can('operator')" class="record-toggle" :class="{ on: recording }" @click="recording = !recording">
          <span class="toggle-dot"></span>
          <span class="toggle-label">{{ recording ? '录制中' : '录制' }}</span>
        </label>
        <button v-if="auth.can('operator')" class="action-btn save" @click="saveScript" :disabled="!steps.length">
          <span class="btn-icon">⤓</span>
          <span>保存脚本</span>
          <em v-if="steps.length" class="badge">{{ steps.length }}</em>
        </button>
      </div>
    </header>

    <!-- 主体区域 -->
    <div class="body">
      <!-- 左侧：投屏画面 + 侧边按键 -->
      <div class="phone-area">
        <div class="phone-wrapper">
          <!-- 光泽装饰 -->
          <div class="phone-gloss"></div>
          <div class="phone-screen" :style="{ aspectRatio: displayRatio }" @mousedown="auth.can('operator') && onPhoneInteract($event)" @click="auth.can('operator') && onPhoneInteract($event)">
            <div v-if="streamError" class="stream-overlay err">
              <div class="overlay-title">投屏不可用</div>
              <div class="overlay-sub">{{ streamError }}</div>
              <button class="retry-btn" @click="retryStream">重试</button>
            </div>
            <iframe
              v-else
              :key="streamKey"
              :src="streamSrc"
              class="stream-iframe"
              frameborder="0"
              allow="fullscreen; autoplay"
              @load="onStreamIframeLoad"
            />
            <!-- 投屏层遮罩（V3）：本端视觉锁定，非服务端占用 -->
            <div v-if="locked" class="lock-overlay">
              <div class="lock-icon">🔒</div>
              <div class="lock-title">本端投屏已锁定</div>
              <div class="lock-meta">锁定人：{{ lockInfo?.by || '—' }}</div>
              <div class="lock-meta">时间：{{ fmtLockTime(lockInfo?.at) }}</div>
              <div class="lock-note">仅本端视觉锁定 + 禁止本端控制；不是服务端占用，其他端不受影响。</div>
              <button class="unlock-btn" :disabled="lockBusy" @click="unlockScreen">
                {{ lockBusy ? '处理中…' : '解除遮罩' }}
              </button>
            </div>
          </div>
        </div>
        <!-- 侧边按键 -->
        <div class="side-keys">
          <button
            v-for="btn in keyButtons"
            :key="btn.key"
            class="key-btn"
            :title="btn.label"
            :disabled="keyBusy || locked"
            @mousedown.prevent="sendKey(btn.key)"
          >
            <span class="key-icon">{{ btn.icon }}</span>
            <span class="key-label">{{ btn.label }}</span>
          </button>
        </div>
      </div>

      <!-- 右侧：功能面板 -->
      <div class="panel">
        <div class="panel-card">
          <div class="card-header">
            <span class="card-icon">🌐</span>
            <span class="card-title">浏览器</span>
          </div>
          <div class="card-body">
            <div class="url-input-row">
              <input
                v-model="url"
                class="url-input"
                placeholder="输入网址…"
                :disabled="locked"
                @keyup.enter="openUrl"
              />
              <button v-if="auth.can('operator')" class="go-btn" :disabled="locked" @click="openUrl">打开</button>
            </div>
          </div>
        </div>

        <div class="panel-card">
          <div class="card-header">
            <span class="card-icon">⚙</span>
            <span class="card-title">显示设置</span>
          </div>
          <div class="card-body">
            <div class="display-row">
              <select
                v-model="displaySel"
                class="display-select"
                :disabled="locked || customOpen"
                @change="pickPreset(displaySel)"
              >
                <option v-for="(p, i) in displayPresets" :key="i" :value="i">{{ p.label }}</option>
              </select>
              <button v-if="auth.can('operator')" class="apply-btn" @click="applyDisplay" :disabled="applying || locked">
                {{ applying ? '切换中…' : '应用' }}
              </button>
            </div>
            <div class="display-custom-toggle">
              <label>
                <input type="checkbox" v-model="customOpen" :disabled="locked" />
                自定义分辨率
              </label>
            </div>
            <div v-if="customOpen" class="display-custom">
              <input v-model.number="customW" class="num-input" type="number" min="320" max="2160" :disabled="locked" />
              <span class="x">×</span>
              <input v-model.number="customH" class="num-input" type="number" min="480" max="3840" :disabled="locked" />
              <span class="x">@</span>
              <input v-model.number="customD" class="num-input" type="number" min="120" max="640" :disabled="locked" />
              <span class="unit">dpi</span>
            </div>
            <div class="display-info">
              当前 {{ device.width }} × {{ device.height }} @ {{ device.dpi }}dpi
            </div>
            <div class="display-info muted">
              原始 {{ device.orig_width || device.width }} × {{ device.orig_height || device.height }}
              @ {{ device.orig_dpi || device.dpi }}dpi
            </div>
            <div class="display-tip">切换后部分后端需重建容器/重启生效（约 10–30s），画面可能短暂断开。</div>
            <button
              v-if="auth.can('operator')"
              class="reset-display-btn"
              :disabled="resetting || applying || locked"
              @click="applyResetDisplay"
            >
              {{ resetting ? '恢复中…' : '恢复原始分辨率/密度' }}
            </button>
          </div>
        </div>

        <div class="panel-card">
          <div class="card-header">
            <span class="card-icon">🎞</span>
            <span class="card-title">投屏渲染质量</span>
          </div>
          <div class="card-body">
            <select
              class="display-select"
              :value="quality"
              :disabled="qualityBusy || locked || !auth.can('operator')"
              @change="changeQuality($event.target.value)"
            >
              <option v-for="q in QUALITY_OPTIONS" :key="q.value" :value="q.value">{{ q.label }}</option>
            </select>
            <div class="display-tip">
              仅调整投屏帧率/码率，不改变设备内渲染实现；本项目无「旧版/新版渲染器」切换项。
            </div>
          </div>
        </div>
      </div>
    </div>

    <ScrcpyPlayer
      v-if="device"
      :device="device"
      v-model:visible="scrcpyOpen"
    />
  </div>
</template>

<style scoped>
/* ================================================================
   Page
   ================================================================ */
.page {
  display: flex;
  flex-direction: column;
  gap: 0;
  height: 100%;
  min-height: 0;
}

/* ================================================================
   Topbar
   ================================================================ */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  background: rgba(255,255,255,.1);
  border-bottom: 1px solid rgba(255,255,255,.16);
  backdrop-filter: blur(12px);
  flex-shrink: 0;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.back-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid rgba(255,255,255,.2);
  border-radius: 8px;
  background: rgba(255,255,255,.12);
  color: #e0e0e4;
  cursor: pointer;
  transition: all .15s;
  font-family: inherit;
  padding: 0;
}
.back-btn:hover {
  background: rgba(255,255,255,.18);
  color: #fff;
}
.back-arrow {
  font-size: 16px;
  line-height: 1;
}

.device-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.device-name {
  font-size: 15px;
  font-weight: 600;
  color: #f0f0f4;
  letter-spacing: .01em;
}
.device-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #a0a0a8;
  font-style: normal;
}
.device-meta em {
  font-style: normal;
}
.device-meta .ip {
  color: #30d158;
}
.sep-dot {
  display: inline-block;
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: rgba(255,255,255,.15);
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 15px;
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 8px;
  background: rgba(255,255,255,.1);
  color: #e0e0e4;
  cursor: pointer;
  font-size: 13px;
  font-family: inherit;
  transition: all .15s;
  white-space: nowrap;
}
.action-btn:hover {
  background: rgba(255,255,255,.18);
  border-color: rgba(255,255,255,.25);
  color: #fff;
}
.action-btn.popout { border-color: rgba(48,209,88,.25); color: #a5f5c0; }
.action-btn.popout:hover { background: rgba(48,209,88,.1); border-color: rgba(48,209,88,.4); }
.action-btn.save { border-color: rgba(64,156,255,.25); color: #a0d0ff; }
.action-btn.save:hover { background: rgba(64,156,255,.1); border-color: rgba(64,156,255,.4); }
.action-btn:disabled { opacity: .35; cursor: default; }
.action-btn.lock { border-color: rgba(255,159,10,.28); color: #ffd60a; }
.action-btn.lock:hover { background: rgba(255,159,10,.1); border-color: rgba(255,159,10,.45); }
.action-btn.lock.on { border-color: rgba(255,69,58,.4); color: #ff9589; background: rgba(255,69,58,.08); }
.btn-icon { font-size: 15px; line-height: 1; }
.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: rgba(64,156,255,.25);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  font-style: normal;
}

/* 录制开关 */
.record-toggle {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 12px;
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 8px;
  background: rgba(255,255,255,.1);
  cursor: pointer;
  transition: all .2s;
  user-select: none;
}
.record-toggle.on {
  border-color: rgba(255,69,58,.35);
  background: rgba(255,69,58,.08);
}
.toggle-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: rgba(255,255,255,.35);
  transition: all .2s;
}
.record-toggle.on .toggle-dot {
  background: #ff453a;
  box-shadow: 0 0 6px rgba(255,69,58,.5);
}
.toggle-label {
  font-size: 13px;
  color: #d0d0d8;
}
.record-toggle.on .toggle-label { color: #ff9589; }

/* ================================================================
   Body
   ================================================================ */
.body {
  display: flex;
  gap: 24px;
  padding: 20px;
  flex: 1;
  min-height: 0;
  align-items: flex-start;
}

/* ================================================================
   Phone Area
   ================================================================ */
.phone-area {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  flex-shrink: 0;
}

.phone-wrapper {
  position: relative;
  flex-shrink: 0;
}

.phone-screen {
  position: relative;
  width: 320px;
  background: #000;
  border-radius: 6px;
  overflow: hidden;
  box-shadow:
    0 0 0 1px rgba(255,255,255,.06),
    0 2px 20px rgba(0,0,0,.4),
    0 8px 40px rgba(0,0,0,.3);
  transition: height 0.35s ease;
}

/* 光泽装饰 */
.phone-gloss {
  position: absolute;
  inset: 0;
  border-radius: 6px;
  pointer-events: none;
  z-index: 2;
  background: linear-gradient(
    135deg,
    rgba(255,255,255,.03) 0%,
    transparent 40%,
    transparent 60%,
    rgba(255,255,255,.01) 100%
  );
}

.stream-iframe {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 0;
  background: #000;
}

/* 错误覆盖层 */
.stream-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #8e8e93;
  background: radial-gradient(ellipse at center, #1c1c20 0%, #0a0a0a 100%);
}

.overlay-title { font-weight: 600; font-size: 14px; color: #e5e5ea; }
.overlay-sub { font-size: 12px; max-width: 240px; text-align: center; }
.stream-overlay.err .overlay-title { color: #ff453a; }
.stream-overlay.err .overlay-sub  { color: #ff9589; }

/* 投屏层遮罩（V3）：本端视觉锁定，非服务端占用 */
.lock-overlay {
  position: absolute;
  inset: 0;
  z-index: 6;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px 18px;
  text-align: center;
  background: rgba(8, 8, 10, 0.9);
  backdrop-filter: blur(6px);
  color: #e5e5ea;
  cursor: not-allowed;
}
.lock-icon { font-size: 34px; line-height: 1; }
.lock-title { font-size: 15px; font-weight: 600; color: #ffd60a; }
.lock-meta { font-size: 12px; color: #b8b8c0; }
.lock-note { font-size: 11px; color: #8e8e93; max-width: 260px; line-height: 1.5; }
.unlock-btn {
  margin-top: 8px;
  padding: 8px 20px;
  border: 1px solid rgba(255,159,10,.4);
  border-radius: 7px;
  background: rgba(255,159,10,.12);
  color: #ffd60a;
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: all .15s;
}
.unlock-btn:hover { background: rgba(255,159,10,.22); border-color: rgba(255,159,10,.6); }
.unlock-btn:disabled { opacity: .5; cursor: default; }

.retry-btn {
  margin-top: 4px;
  padding: 7px 20px;
  border: 1px solid rgba(64,156,255,.3);
  border-radius: 6px;
  background: rgba(64,156,255,.1);
  color: #a0d0ff;
  cursor: pointer;
  font-size: 13px;
  font-family: inherit;
  transition: all .15s;
}
.retry-btn:hover {
  background: rgba(64,156,255,.2);
  border-color: rgba(64,156,255,.5);
}

/* ================================================================
   Side Keys
   ================================================================ */
.side-keys {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 2px;
}

.key-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid rgba(255,255,255,.16);
  border-radius: 8px;
  background: rgba(255,255,255,.1);
  color: #d8d8e0;
  cursor: pointer;
  transition: all .15s;
  font-size: 13px;
  font-family: inherit;
  white-space: nowrap;
}
.key-btn:hover {
  background: rgba(255,255,255,.18);
  border-color: rgba(255,255,255,.24);
  color: #fff;
  transform: translateY(-1px);
}
.key-btn:active {
  background: rgba(255,255,255,.22);
  transform: scale(.96) translateY(0);
}
.key-btn:disabled {
  opacity: .3;
  cursor: default;
  transform: none;
}

.key-icon {
  font-size: 15px;
  width: 20px;
  text-align: center;
  line-height: 1;
  opacity: .8;
}
.key-btn:hover .key-icon { opacity: 1; }
.key-label {
  font-weight: 500;
  font-size: 12px;
}

/* ================================================================
   Panel (right side cards)
   ================================================================ */
.panel {
  flex: 1;
  max-width: 480px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.panel-card {
  background: rgba(255,255,255,.1);
  border: 1px solid rgba(255,255,255,.16);
  border-radius: 12px;
  overflow: hidden;
  transition: border-color .2s;
}
.panel-card:hover {
  border-color: rgba(255,255,255,.24);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 18px 0;
}
.card-icon { font-size: 15px; }
.card-title {
  font-size: 13px;
  font-weight: 600;
  color: #d0d0d8;
  text-transform: uppercase;
  letter-spacing: .04em;
}

.card-body {
  padding: 12px 18px 16px;
}

/* 地址栏 */
.url-input-row {
  display: flex;
  gap: 0;
}
.url-input {
  flex: 1;
  padding: 9px 14px;
  border: 1px solid rgba(255,255,255,.22);
  border-right: none;
  border-radius: 7px 0 0 7px;
  background: rgba(0,0,0,.5);
  color: #eeeef2;
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: border-color .15s;
}
.url-input:focus {
  border-color: rgba(64,156,255,.55);
}
.url-input::placeholder {
  color: rgba(255,255,255,.35);
}
.go-btn {
  padding: 9px 18px;
  border: 1px solid rgba(64,156,255,.3);
  border-radius: 0 7px 7px 0;
  background: rgba(64,156,255,.12);
  color: #a0d0ff;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: all .15s;
  white-space: nowrap;
}
.go-btn:hover {
  background: rgba(64,156,255,.22);
  border-color: rgba(64,156,255,.5);
}
.go-btn:disabled { opacity: .35; cursor: default; }

/* 显示设置 */
.display-row {
  display: flex;
  gap: 10px;
  align-items: center;
}
.display-select {
  flex: 1;
  padding: 9px 12px;
  border: 1px solid rgba(255,255,255,.22);
  border-radius: 7px;
  background: rgba(0,0,0,.5);
  color: #eeeef2;
  font-size: 13px;
  font-family: inherit;
  outline: none;
  cursor: pointer;
  transition: border-color .15s;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23666'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  padding-right: 28px;
}
.display-select:focus {
  border-color: rgba(64,156,255,.55);
}
.display-select option {
  background: #1c1c20;
  color: #e0e0e4;
}

.apply-btn {
  padding: 9px 18px;
  border: 1px solid rgba(48,209,88,.25);
  border-radius: 7px;
  background: rgba(48,209,88,.08);
  color: #a5f5c0;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: all .15s;
  white-space: nowrap;
}
.apply-btn:hover {
  background: rgba(48,209,88,.16);
  border-color: rgba(48,209,88,.4);
}
.apply-btn:disabled {
  opacity: .4;
  cursor: default;
}

.display-info {
  margin-top: 10px;
  font-size: 12px;
  color: rgba(255,255,255,.5);
  letter-spacing: .02em;
}
.display-info.muted { color: rgba(255,255,255,.32); margin-top: 4px; }
.display-tip {
  margin-top: 8px;
  font-size: 11px;
  line-height: 1.5;
  color: rgba(255,255,255,.4);
}
.display-custom-toggle {
  margin-top: 8px;
  font-size: 12px;
  color: rgba(255,255,255,.55);
}
.display-custom-toggle label { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
.display-custom {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}
.num-input {
  width: 74px;
  padding: 7px 8px;
  border: 1px solid rgba(255,255,255,.22);
  border-radius: 6px;
  background: rgba(0,0,0,.5);
  color: #eeeef2;
  font-size: 12px;
  font-family: inherit;
  outline: none;
}
.num-input:focus { border-color: rgba(64,156,255,.55); }
.display-custom .x, .display-custom .unit { font-size: 12px; color: rgba(255,255,255,.45); }
.reset-display-btn {
  width: 100%;
  margin-top: 10px;
  padding: 8px 0;
  border: 1px solid rgba(255,159,10,.3);
  border-radius: 7px;
  background: rgba(255,159,10,.1);
  color: #ffc78a;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: all .15s;
}
.reset-display-btn:hover { background: rgba(255,159,10,.18); }
.reset-display-btn:disabled { opacity: .4; cursor: default; }
</style>
