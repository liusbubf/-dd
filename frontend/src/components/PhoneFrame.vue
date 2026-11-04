<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  device: { type: Object, required: true },
  frame: { type: String, default: '' },
  selectable: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
  clickable: { type: Boolean, default: false }, // 点击画面 -> 映射为设备坐标 tap
  typeable: { type: Boolean, default: false }, // 启用画面内文本输入（中文 IME）
  swipeable: { type: Boolean, default: false }, // 启用鼠标拖拽滑动（上/下/左/右）
})
const emit = defineEmits(['open', 'toggle', 'tap', 'text', 'swipe', 'key'])

// 注意：不能用 btoa()，它无法编码中文（"加载中…"）会抛 InvalidCharacterError，
// 导致整个 PhoneFrame 渲染失败、预览页白屏。用 encodeURIComponent 生成 data URL 即可支持 Unicode。
const placeholder =
  'data:image/svg+xml,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="410"><rect width="220" height="410" fill="#111"/><text x="110" y="205" fill="#666" font-size="14" text-anchor="middle">加载中…</text></svg>',
  )

const src = computed(() => props.frame || placeholder)

// 隐藏 textarea 用于捕获中文 IME（compositionstart/end 只在可编辑元素上触发，
// 而 .phone 是普通 div）。屏幕点击时聚焦，用户即可直接在云手机画面内打字。
const imeEl = ref(null)
let composing = false
let justComposed = false

function focusIme() {
  if (props.typeable) imeEl.value?.focus()
}

function onKeydown(e) {
  if (!props.typeable) return
  if (composing) return // 组合输入期间交给 compositionend 发送，跳过 keydown
  if (justComposed) {
    // 组合结束后的回车（IME 确认上屏）不应再次发送
    justComposed = false
    if (e.key === 'Enter') {
      e.preventDefault()
      return
    }
  }
  if (e.key === 'Enter') {
    e.preventDefault()
    const t = imeEl.value?.value || ''
    if (t) emit('text', t)
    if (imeEl.value) imeEl.value.value = ''
    // 发送回车键到云手机，触发输入栏查询/搜索
    emit('key', 'enter')
  } else if (e.key === 'Backspace') {
    // 退格键 -> 云手机删除光标前字符
    e.preventDefault()
    emit('key', 'del')
  } else if (e.key === 'Delete') {
    // Delete 键 -> 云手机删除光标后字符
    e.preventDefault()
    emit('key', 'forward_del')
  } else if (e.key.length === 1) {
    // 单个可打印字符（ASCII）即时发送
    e.preventDefault()
    emit('text', e.key)
  }
}

function onCompositionStart() {
  composing = true
}

function onCompositionEnd(e) {
  composing = false
  justComposed = true
  const t = e.data || imeEl.value?.value || ''
  if (t) emit('text', t)
  if (imeEl.value) imeEl.value.value = ''
}

// 拖拽滑动：pointerdown 记录起点并捕获指针，pointerup 判定位移并折算到设备坐标。
// 用 setPointerCapture 保证鼠标移出画面时仍能收到 pointerup，上滑删除不会中途丢手势。
let swipeStart = null
let suppressClick = false

function onPointerDown(e) {
  if (!props.swipeable || e.button !== 0) return
  swipeStart = { x: e.clientX, y: e.clientY, t: Date.now() }
  e.currentTarget.setPointerCapture?.(e.pointerId)
}

function onPointerUp(e) {
  if (!swipeStart) return
  const start = swipeStart
  swipeStart = null
  const dx = e.clientX - start.x
  const dy = e.clientY - start.y
  const dist = Math.hypot(dx, dy)
  if (dist < 3) return // 位移太小视为点击，交给 click 处理（3px 阈值让「轻轻滑动」即可触发）
  suppressClick = true
  setTimeout(() => { suppressClick = false }, 0)
  const rect = e.currentTarget.getBoundingClientRect()
  const sx = props.device.width / rect.width
  const sy = props.device.height / rect.height
  emit('swipe', {
    x1: Math.round((start.x - rect.left) * sx),
    y1: Math.round((start.y - rect.top) * sy),
    x2: Math.round((e.clientX - rect.left) * sx),
    y2: Math.round((e.clientY - rect.top) * sy),
    duration_ms: Date.now() - start.t,
  })
}

// 鼠标滚轮：仅在 clickable/swipeable 模式（单机操控页）拦截为云手机上下滑动；
//              多画面预览/批量页等非 clickable 模式下，让滚轮正常用于页面滚动（含中键/触摸板）。
// 节流避免滚轮高频触发过多滑动。
let lastWheelTs = 0
function onWheel(e) {
  if (!props.clickable && !props.swipeable) return
  if (!props.swipeable) return
  const now = Date.now()
  if (now - lastWheelTs < 200) return
  lastWheelTs = now
  e.preventDefault()
  const w = props.device.width
  const h = props.device.height
  // 滚轮向上（deltaY<0）= 页面向上滚动 = 查看上方 = 手指下滑（从上往下）
  const wheelUp = e.deltaY < 0
  emit('swipe', wheelUp
    ? { x1: Math.round(w / 2), y1: Math.round(h * 0.3), x2: Math.round(w / 2), y2: Math.round(h * 0.8), duration_ms: 300 }
    : { x1: Math.round(w / 2), y1: Math.round(h * 0.8), x2: Math.round(w / 2), y2: Math.round(h * 0.3), duration_ms: 300 })
}

// 预览画布固定 440x820（后端渲染坐标系）；点击折算到设备真实分辨率
function onClick(e) {
  if (suppressClick) return
  focusIme()
  if (!props.clickable) return emit('open', props.device)
  const rect = e.currentTarget.getBoundingClientRect()
  const rx = (e.clientX - rect.left) / rect.width
  const ry = (e.clientY - rect.top) / rect.height
  emit('tap', {
    x: Math.round(rx * props.device.width),
    y: Math.round(ry * props.device.height),
  })
}
</script>

<template>
  <div
    class="phone"
    :style="{ outline: selected ? '3px solid #0a84ff' : 'none' }"
    @click="onClick"
    @pointerdown="onPointerDown"
    @pointerup="onPointerUp"
    @wheel="onWheel"
  >
    <img :src="src" :alt="device.name" draggable="false" />
    <el-checkbox
      v-if="selectable"
      class="selbox"
      :model-value="selected"
      @change="$emit('toggle', device)"
      @click.stop
    />
    <textarea
      v-if="typeable"
      ref="imeEl"
      class="ime-input"
      @keydown="onKeydown"
      @compositionstart="onCompositionStart"
      @compositionend="onCompositionEnd"
    ></textarea>
    <div class="cap">
      <span class="dot" :class="device.status"></span>{{ device.name }}
      <span style="float: right; opacity: 0.85">{{ device.fingerprint?.network?.exit_ip }}</span>
    </div>
  </div>
</template>

<style scoped>
.ime-input {
  position: fixed;
  top: 0;
  left: 0;
  width: 1px;
  height: 1px;
  opacity: 0;
  border: 0;
  padding: 0;
  pointer-events: none;
}
</style>
