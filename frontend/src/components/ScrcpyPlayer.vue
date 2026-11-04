<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { api } from '../api/client'

const props = defineProps({
  device: { type: Object, required: true },
  visible: { type: Boolean, default: false },
})
const emit = defineEmits(['update:visible'])

const loading = ref(false)
const errorMsg = ref('')
const info = ref(null)
const iframeReady = ref(false)
const reloadKey = ref(0)
const keyBusy = ref(false)

const iframeSrc = computed(() => info.value?.iframe_url || '')

const deviceRatio = computed(() => {
  const w = props.device?.width || 720
  const h = props.device?.height || 1280
  return `${w} / ${h}`
})

async function prepare() {
  loading.value = true
  errorMsg.value = ''
  info.value = null
  iframeReady.value = false
  try {
    const { data } = await api.control(props.device.id, 'scrcpy', { action: 'prepare' }, { timeout: 15000 })
    if (!data.ok) { errorMsg.value = '后端返回失败'; return }
    if (!data.ready) { errorMsg.value = 'ws-scrcpy 服务未就绪或设备不可达'; return }
    info.value = data
  } catch (e) {
    errorMsg.value = e.message || '请求失败'
  } finally {
    loading.value = false
  }
}

watch(() => props.visible, async (v) => {
  if (v) {
    reloadKey.value++
    await prepare()
  } else {
    info.value = null
    iframeReady.value = false
  }
}, { immediate: true })

onBeforeUnmount(() => { info.value = null })

function onIframeLoad() { iframeReady.value = true }
function close() { emit('update:visible', false) }
function refreshIframe() { reloadKey.value++; iframeReady.value = false; prepare() }

async function sendKey(key) {
  if (keyBusy.value) return
  keyBusy.value = true
  try {
    await api.control(props.device.id, 'key', { key })
  } catch { /* 静默 */ }
  finally { keyBusy.value = false }
}

const keyButtons = [
  { key: 'power',       icon: '⏻', label: '电源' },
  { key: 'volume_up',   icon: '🔊', label: '音量+' },
  { key: 'volume_down', icon: '🔉', label: '音量-' },
  { key: 'back',        icon: '◀',  label: '返回' },
  { key: 'home',        icon: '●',  label: '主页' },
  { key: 'recent',      icon: '▣',  label: '任务' },
]
</script>

<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="(v) => emit('update:visible', v)"
    top="1vh"
    center
    append-to-body
    :close-on-click-modal="false"
    destroy-on-close
    :show-close="false"
    class="scrcpy-dialog"
  >
    <div class="layout">
      <!-- 主体：手机框 + 侧边按键 -->
      <div class="main-row">
        <!-- 手机框 -->
        <div class="phone-frame">
          <div class="phone-screen" :style="{ aspectRatio: deviceRatio }">
            <div v-if="loading" class="state-overlay">
              <el-icon class="is-loading" :size="40"><Loading /></el-icon>
              <div class="state-title">正在连接设备…</div>
            </div>
            <div v-else-if="errorMsg" class="state-overlay err">
              <div class="state-title">投屏不可用</div>
              <div class="state-sub">{{ errorMsg }}</div>
              <el-button size="small" type="primary" style="margin-top: 14px" @click="prepare">重试</el-button>
            </div>
            <template v-else-if="info">
              <iframe
                :key="reloadKey"
                :src="iframeSrc"
                class="screen-iframe"
                frameborder="0"
                allow="fullscreen; autoplay"
                @load="onIframeLoad"
              />
              
            </template>
          </div>
        </div>

        <!-- 侧边控制按键 -->
        <div class="side-keys">
          <button
            v-for="btn in keyButtons"
            :key="btn.key"
            class="key-btn"
            :title="btn.label"
            :disabled="keyBusy"
            @mousedown.prevent="sendKey(btn.key)"
          >
            <span class="key-icon">{{ btn.icon }}</span>
            <span class="key-label">{{ btn.label }}</span>
          </button>
        </div>
      </div>

      <!-- 底部操作栏 -->
      <div class="controls">
        <div class="header">
          <span class="live-dot" />
          <span class="title">实时投屏</span>
          <span class="device" v-if="device">{{ device.name }}</span>
        </div>
        <div class="btn-group">
          <el-button size="small" @click="refreshIframe" :loading="loading">刷新</el-button>
          <el-button size="small" type="primary" @click="close">关闭</el-button>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

/* ===== 主体行：手机框 + 侧边键 ===== */
.main-row {
  display: flex;
  align-items: stretch;
  gap: 14px;
}

/* ===== 手机框 ===== */
.phone-frame {
  padding: 10px 12px;
  background: #1a1a1e;
  border-radius: 28px;
  box-shadow:
    0 0 0 2px #2c2c2e,
    0 0 0 4px #1a1a1e,
    0 0 0 5px rgba(255,255,255,.04),
    0 24px 80px rgba(0,0,0,.55);
}

.phone-screen {
  position: relative;
  width: 360px;
  background: #000;
  border-radius: 16px;
  overflow: hidden;
}

.screen-iframe {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 0;
  background: #000;
}

/* ===== 状态覆盖层 ===== */
.state-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #8e8e93;
  background: radial-gradient(ellipse at center, #1c1c20 0%, #0a0a0a 100%);
}
.state-overlay .state-title { font-weight: 600; font-size: 14px; color: #e5e5ea; }
.state-overlay .state-sub { font-size: 12px; max-width: 260px; text-align: center; }
.state-overlay.err .state-title { color: #ff453a; }
.state-overlay.err .state-sub  { color: #ff9589; }


@keyframes dot-pulse {
  0%,100% { opacity: 1; transform: scale(1); }
  50% { opacity: .3; transform: scale(1.5); }
}

/* ===== 侧边按键 ===== */
.side-keys {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
  padding: 10px 0;
}

.key-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 10px;
  background: rgba(255,255,255,.04);
  color: #d1d1d6;
  cursor: pointer;
  transition: all .15s;
  min-width: 100px;
  font-size: 13px;
}
.key-btn:hover {
  background: rgba(255,255,255,.1);
  border-color: rgba(255,255,255,.15);
  color: #fff;
}
.key-btn:active {
  background: rgba(255,255,255,.16);
  transform: scale(.96);
}
.key-btn:disabled {
  opacity: .35;
  cursor: default;
  transform: none;
}

.key-icon {
  font-size: 16px;
  width: 24px;
  text-align: center;
  line-height: 1;
}
.key-label {
  font-weight: 500;
}

/* ===== 底部操作栏 ===== */
.controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: calc(360px + 20px);
  padding: 0 4px;
}
.header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.live-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #30d158;
  box-shadow: 0 0 0 2px rgba(48,209,88,.18);
  animation: dot-pulse 1.8s ease-in-out infinite;
}
.header .title { font-weight: 700; font-size: 14px; color: #e5e5ea; }
.header .device { color: #86868b; font-size: 12px; }
.btn-group { display: flex; gap: 8px; }

/* ===== Element Plus dialog ===== */
:deep(.el-overlay) {
  background: rgba(0, 0, 0, 0.15) !important;
}
:deep(.el-dialog__wrapper) {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
}
:deep(.el-dialog) {
  --el-dialog-bg-color: transparent !important;
  --el-dialog-width: unset !important;
  width: fit-content !important;
  min-width: unset !important;
  max-width: unset !important;
  background: transparent !important;
  box-shadow: none !important;
  border: none !important;
}
:deep(.el-dialog__header) {
  display: none !important;
  background: transparent !important;
}
:deep(.el-dialog__body) {
  padding: 20px 16px 24px !important;
  background: transparent !important;
}
</style>

<style>
/* 全局样式：覆盖 Element Plus 弹窗，不受 scoped 限制 */
.scrcpy-dialog {
  --el-dialog-bg-color: transparent !important;
  --el-dialog-width: auto !important;
  background-color: transparent !important;
  background: transparent !important;
  width: fit-content !important;
  min-width: unset !important;
  max-width: unset !important;
  box-shadow: none !important;
  border: none !important;
}
.scrcpy-dialog .el-dialog__header {
  display: none !important;
  background: transparent !important;
}
.scrcpy-dialog .el-dialog__body {
  padding: 20px 16px 24px !important;
  background: transparent !important;
}
.scrcpy-dialog .el-dialog__headerbtn {
  display: none !important;
}
.scrcpy-dialog + .el-overlay,
.el-overlay:has(+ .scrcpy-dialog),
.el-overlay:has(.scrcpy-dialog) {
  background: rgba(0, 0, 0, 0.15) !important;
}
</style>