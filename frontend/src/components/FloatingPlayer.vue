<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'

const props = defineProps({
  device: { type: Object, required: true },
  visible: { type: Boolean, default: true },
  offset: { type: Number, default: 0 },
  zIndex: { type: Number, default: 1100 },
  canWrite: { type: Boolean, default: undefined },
})
const emit = defineEmits(['update:visible', 'open-page', 'focus', 'changed'])

const auth = useAuth()
const writable = computed(() => (props.canWrite === undefined ? auth.can('operator') : props.canWrite))

const LAYOUT_KEY = `float.layout.${props.device.id}`
const SIZE_KEY = `float.size.${props.device.id}`

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || 'null') || fallback
  } catch {
    return fallback
  }
}

// 位置/尺寸记忆（每个设备独立）；首次出现按 offset 错开
const saved = loadJson(LAYOUT_KEY, null)
const pos = reactive({
  x: saved?.x ?? Math.max(12, window.innerWidth - 430 - props.offset * 28),
  y: saved?.y ?? 96 + props.offset * 24,
})
const width = ref(loadJson(SIZE_KEY, 360))
const maximized = ref(false)
const winRef = ref(null)

function persist() {
  localStorage.setItem(LAYOUT_KEY, JSON.stringify({ x: pos.x, y: pos.y }))
  localStorage.setItem(SIZE_KEY, String(width.value))
}

// —— 拖动 ——
let drag = null
function startDrag(e) {
  if (maximized.value) return
  drag = { dx: e.clientX - pos.x, dy: e.clientY - pos.y }
  window.addEventListener('pointermove', onDrag)
  window.addEventListener('pointerup', endDrag)
}
function onDrag(e) {
  if (!drag) return
  const maxX = window.innerWidth - 80
  const maxY = window.innerHeight - 60
  pos.x = Math.min(maxX, Math.max(-width.value + 80, e.clientX - drag.dx))
  pos.y = Math.min(maxY, Math.max(8, e.clientY - drag.dy))
}
function endDrag() {
  drag = null
  window.removeEventListener('pointermove', onDrag)
  window.removeEventListener('pointerup', endDrag)
  persist()
}

// —— 缩放（右下角把手） ——
let resizing = null
function startResize(e) {
  if (maximized.value) return
  resizing = { startX: e.clientX, startW: width.value }
  window.addEventListener('pointermove', onResize)
  window.addEventListener('pointerup', endResize)
}
function onResize(e) {
  if (!resizing) return
  width.value = clampSize(resizing.startW + (e.clientX - resizing.startX))
}
function endResize() {
  resizing = null
  window.removeEventListener('pointermove', onResize)
  window.removeEventListener('pointerup', endResize)
  persist()
}
function clampSize(v) {
  return Math.max(240, Math.min(1080, Math.round(v)))
}
function pickSize(v) {
  width.value = v
  persist()
}

// —— 预览帧 ——
const frame = ref('')
const playing = ref(true)
const loading = ref(false)
const errMsg = ref('')
let timer = null

async function refresh() {
  if (loading.value) return
  loading.value = true
  try {
    const r = await api.screenshot(props.device.id, { fresh: true })
    frame.value = r.data?.frame || ''
    errMsg.value = ''
  } catch (e) {
    errMsg.value = e?.response?.data?.detail || e.message || '截图获取失败'
  } finally {
    loading.value = false
  }
}
function startPoll() {
  stopPoll()
  refresh()
  timer = setInterval(refresh, 1000)
}
function stopPoll() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
watch(playing, (on) => (on ? startPoll() : stopPoll()))
startPoll()
onBeforeUnmount(stopPoll)

const aspect = computed(() => props.device.height / props.device.width || 16 / 9)
const bodyStyle = computed(() => ({
  width: maximized.value ? '100%' : '100%',
  aspectRatio: `${1} / ${aspect.value}`,
}))

// —— 菜单（11 项，逐条对应能力；缺后端的一律禁用并说明） ——
const busy = ref(false)
const MENU = [
  { key: 'start', label: '开机', icon: 'VideoPlay', need: 'operator' },
  { key: 'stop', label: '关机', icon: 'VideoPause', need: 'operator' },
  { key: 'restart', label: '重启', icon: 'RefreshRight', need: 'operator' },
  { key: 'restore', label: '恢复快照', icon: 'RefreshLeft', need: 'operator' },
  { key: 'wipe', label: '清空数据', icon: 'Delete', need: 'operator', danger: true },
  { key: 'share', label: '共享', icon: 'Share', need: 'operator' },
  { key: 'unshare', label: '取消共享', icon: 'TurnOff', need: 'operator' },
  { key: 'group', label: '移动分组', icon: 'FolderOpened', need: 'operator' },
  { key: 'unlock', label: '清理屏锁', icon: 'Unlock', need: 'operator', danger: true },
  { key: 'shot', label: '高清截图', icon: 'Camera' },
  { key: 'morph', label: '改机', icon: 'Cpu', disabled: true, reason: '需后端能力：设备指纹重随机 / 改机接口（当前未实现）' },
]

function itemDisabled(item) {
  return item.disabled || (item.need && !auth.can(item.need)) || busy.value
}
function tooltipOf(item) {
  if (item.disabled) return item.reason
  if (item.need && !auth.can(item.need)) return '当前角色无操作权限'
  return item.label
}

async function run(item) {
  if (itemDisabled(item)) return
  emit('focus')
  busy.value = true
  try {
    switch (item.key) {
      case 'start':
        await api.startDevice(props.device.id)
        ElMessage.success('已发送开机指令')
        break
      case 'stop':
        await api.stopDevice(props.device.id)
        ElMessage.success('已发送关机指令')
        break
      case 'restart':
        await api.restartDevice(props.device.id)
        ElMessage.success('已发送重启指令')
        break
      case 'restore':
        await confirmAndReset('restore')
        break
      case 'wipe':
        await confirmAndReset('wipe')
        break
      case 'share':
        await openShare()
        break
      case 'unshare':
        await openShares()
        break
      case 'group':
        await openGroup()
        break
      case 'unlock':
        await confirmUnlock()
        break
      case 'shot':
        await shot()
        break
      default:
        break
    }
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error(e?.response?.data?.detail || e.message || '操作失败')
    }
  } finally {
    busy.value = false
  }
  emit('changed')
  refresh()
}

async function confirmAndReset(kind) {
  const word = props.device.name
  const title = kind === 'wipe' ? '清空设备数据' : '恢复到最近快照'
  const tip =
    kind === 'wipe'
      ? `将清空「${word}」内的应用与用户数据，设备保留。请输入设备名确认：`
      : `将把「${word}」恢复到最近一次可用快照。请输入设备名确认：`
  const { value } = await ElMessageBox.prompt(tip, title, {
    confirmButtonText: '确认执行',
    cancelButtonText: '取消',
    type: 'warning',
    inputPlaceholder: word,
    inputValidator: (v) => v === word || '设备名不一致',
  })
  if (value !== word) return
  if (kind === 'wipe') await api.wipeDeviceData(props.device.id, word)
  else await api.restoreLatestSnapshot(props.device.id, word)
  ElMessage.success(kind === 'wipe' ? '已提交清空数据' : '已提交恢复快照')
}

async function confirmUnlock() {
  await ElMessageBox.confirm(
    `将清理「${props.device.name}」的屏幕锁定遮罩（会写审计）。确认继续？`,
    '清理屏锁',
    { type: 'warning', confirmButtonText: '清理', cancelButtonText: '取消' },
  )
  await api.unlockDevice(props.device.id)
  ElMessage.success('屏锁遮罩已清理')
}

async function shot() {
  const r = await api.screenshot(props.device.id, { fresh: true, hd: true })
  shotImg.value = r.data?.frame || ''
  shotDlg.value = true
}

// 共享
const shareDlg = ref(false)
const shareLoading = ref(false)
const candidates = ref([])
const shareUserId = ref(null)
async function openShare() {
  shareDlg.value = true
  shareLoading.value = true
  try {
    const r = await api.shareCandidates(props.device.id)
    candidates.value = r.data || []
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载可共享用户失败')
    shareDlg.value = false
  } finally {
    shareLoading.value = false
  }
}
async function doShare() {
  if (!shareUserId.value) return ElMessage.warning('请选择用户')
  await api.createDeviceShare(props.device.id, shareUserId.value)
  ElMessage.success('已共享')
  shareDlg.value = false
  shareUserId.value = null
}

const sharesDlg = ref(false)
const shares = ref([])
const sharesLoading = ref(false)
async function openShares() {
  sharesDlg.value = true
  sharesLoading.value = true
  try {
    const r = await api.listDeviceShares(props.device.id)
    shares.value = r.data || []
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载共享列表失败')
  } finally {
    sharesLoading.value = false
  }
}
async function revoke(share) {
  await api.revokeDeviceShare(props.device.id, share.id)
  shares.value = shares.value.filter((s) => s.id !== share.id)
  ElMessage.success('已取消共享')
}

// 分组
const groupDlg = ref(false)
const groups = ref([])
const groupId = ref(null)
async function openGroup() {
  groupDlg.value = true
  try {
    const r = await api.listGroups()
    groups.value = r.data || []
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载分组失败')
  }
}
async function doMoveGroup() {
  if (!groupId.value) {
    await api.updateDevice(props.device.id, { group_id: null })
  } else {
    await api.moveGroupDevices(groupId.value, { device_ids: [props.device.id] })
  }
  ElMessage.success('分组已更新')
  groupDlg.value = false
}

// 截图
const shotDlg = ref(false)
const shotImg = ref('')

// 最大化 / 关闭
function toggleMax() {
  maximized.value = !maximized.value
}
function close() {
  emit('update:visible', false)
}
function downloadShot() {
  const a = document.createElement('a')
  a.href = shotImg.value
  a.download = `${props.device.name}-${Date.now()}.svg`
  a.click()
}
</script>

<template>
  <teleport to="body">
    <div
      v-if="visible"
      ref="winRef"
      class="float-win"
      :class="{ maximized }"
      :style="
        maximized
          ? { zIndex }
          : { left: `${pos.x}px`, top: `${pos.y}px`, width: `${width}px`, zIndex }
      "
      @pointerdown="emit('focus')"
    >
      <!-- 顶部条：设备名 + 编号 + 窗口控制 -->
      <header class="fw-head" @pointerdown="startDrag">
        <span class="fw-dot" :class="{ on: device.status === 'running' }"></span>
        <span class="fw-name" :title="device.name">{{ device.name }}</span>
        <span class="fw-id">#{{ device.id }}</span>
        <span class="fw-spacer"></span>
        <el-tooltip content="刷新画面" placement="bottom">
          <button class="fw-btn" type="button" @click.stop="refresh()"><el-icon><Refresh /></el-icon></button>
        </el-tooltip>
        <el-tooltip :content="maximized ? '还原窗口' : '最大化'" placement="bottom">
          <button class="fw-btn" type="button" @click.stop="toggleMax">
            <el-icon><FullScreen v-if="!maximized" /><ScaleToOriginal v-else /></el-icon>
          </button>
        </el-tooltip>
        <el-tooltip content="在独立页打开" placement="bottom">
          <button class="fw-btn" type="button" @click.stop="emit('open-page', device)"><el-icon><TopRight /></el-icon></button>
        </el-tooltip>
        <el-tooltip content="关闭" placement="bottom">
          <button class="fw-btn danger" type="button" @click.stop="close"><el-icon><Close /></el-icon></button>
        </el-tooltip>
      </header>

      <!-- 尺寸条：预设 + 连续滑杆 + 当前值 -->
      <div class="fw-sizebar">
        <button
          v-for="s in [480, 720, 1080]"
          :key="s"
          class="size-chip"
          :class="{ active: width === s }"
          type="button"
          @click.stop="pickSize(s)"
        >
          {{ s }}
        </button>
        <el-slider
          :model-value="width"
          :min="240"
          :max="1080"
          :step="20"
          size="small"
          :show-tooltip="false"
          class="size-slider"
          @update:model-value="pickSize"
        />
        <span class="size-value">{{ width }}px</span>
      </div>

      <!-- 画面 + 右侧竖排图标条 -->
      <div class="fw-body">
        <div class="fw-screen" :style="bodyStyle" @click="emit('open-page', device)">
          <img v-if="frame" :src="frame" alt="设备画面" draggable="false" />
          <div v-else class="fw-screen-empty">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>正在获取画面…</span>
          </div>
          <div v-if="errMsg" class="fw-error">
            <el-icon><WarningFilled /></el-icon>
            <span>{{ errMsg }}</span>
          </div>
          <span class="fw-badge">演示 / 预览</span>
        </div>

        <aside class="fw-rail">
          <el-tooltip v-for="item in MENU" :key="item.key" :content="tooltipOf(item)" placement="left">
            <button
              class="rail-btn"
              :class="{ danger: item.danger, disabled: itemDisabled(item), unavailable: item.disabled }"
              type="button"
              :disabled="itemDisabled(item)"
              @click.stop="run(item)"
            >
              <el-icon><component :is="item.icon" /></el-icon>
            </button>
          </el-tooltip>
        </aside>
      </div>

      <div class="fw-foot">
        <span class="foot-meta">{{ device.width }}×{{ device.height }} @{{ device.dpi }}dpi</span>
        <span class="foot-spacer"></span>
        <button class="foot-link" type="button" @click="playing = !playing">
          {{ playing ? '暂停预览' : '继续预览' }}
        </button>
      </div>

      <div v-if="!maximized" class="fw-resize" title="拖动缩放" @pointerdown.stop="startResize"></div>
    </div>

    <el-dialog v-model="shareDlg" title="共享云机" width="380px" append-to-body>
      <div v-loading="shareLoading">
        <el-select v-model="shareUserId" placeholder="选择同租户用户" style="width: 100%">
          <el-option
            v-for="c in candidates"
            :key="c.id || c.user_id"
            :label="`${c.username}${c.role ? ' · ' + c.role : ''}`"
            :value="c.id || c.user_id"
          />
        </el-select>
        <p class="dlg-tip">共享后对方可在设备列表中看到并操控该云机；可随时在「取消共享」里撤销。</p>
      </div>
      <template #footer>
        <el-button @click="shareDlg = false">取消</el-button>
        <el-button type="primary" @click="doShare">共享</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="sharesDlg" title="已共享给" width="420px" append-to-body>
      <div v-loading="sharesLoading">
        <div v-if="!shares.length" class="dlg-tip">当前没有共享记录</div>
        <div v-for="s in shares" :key="s.id" class="share-row">
          <span>{{ s.username || s.user_name || `用户 ${s.user_id}` }}</span>
          <el-button size="small" type="danger" plain @click="revoke(s)">撤销</el-button>
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="groupDlg" title="移动分组" width="360px" append-to-body>
      <el-select v-model="groupId" placeholder="选择分组（留空为移出）" style="width: 100%">
        <el-option label="不分组" :value="0" />
        <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />
      </el-select>
      <template #footer>
        <el-button @click="groupDlg = false">取消</el-button>
        <el-button type="primary" @click="doMoveGroup">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="shotDlg" title="高清截图" width="520px" append-to-body>
      <img v-if="shotImg" :src="shotImg" alt="截图" class="shot-img" />
      <template #footer>
        <el-button @click="shotDlg = false">关闭</el-button>
        <el-button type="primary" @click="downloadShot">下载</el-button>
      </template>
    </el-dialog>
  </teleport>
</template>

<style scoped>
.float-win {
  position: fixed;
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  font-size: var(--font-xs);
  color: var(--color-text-primary);
}
.float-win.maximized {
  left: 12px !important;
  top: 12px !important;
  width: calc(100vw - 24px) !important;
  height: calc(100vh - 24px);
}
.fw-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  height: 34px;
  background: var(--color-bg-elevated);
  border-bottom: 1px solid var(--color-border);
  cursor: move;
  user-select: none;
}
.fw-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-text-muted);
  flex: none;
}
.fw-dot.on {
  background: var(--color-success);
  box-shadow: 0 0 8px color-mix(in srgb, var(--color-success) 60%, transparent);
}
.fw-name {
  font-weight: 600;
  max-width: 42%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fw-id {
  font-family: Consolas, monospace;
  color: var(--color-text-muted);
}
.fw-spacer {
  flex: 1;
}
.fw-btn {
  border: none;
  background: transparent;
  color: var(--color-text-secondary);
  width: 24px;
  height: 24px;
  border-radius: var(--radius-sm);
  display: inline-grid;
  place-items: center;
  cursor: pointer;
}
.fw-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}
.fw-btn.danger:hover {
  background: var(--color-danger-weak);
  color: var(--color-danger);
}
.fw-sizebar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-surface);
}
.size-chip {
  border: 1px solid var(--color-border);
  background: var(--color-bg-elevated);
  color: var(--color-text-secondary);
  font-size: 11px;
  border-radius: var(--radius-sm);
  padding: 1px 6px;
  cursor: pointer;
}
.size-chip.active {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-weak);
}
.size-slider {
  flex: 1;
  min-width: 60px;
  margin: 0 4px;
}
.size-value {
  font-family: Consolas, monospace;
  color: var(--color-text-muted);
  white-space: nowrap;
}
.fw-body {
  display: flex;
  min-height: 0;
  background: var(--color-bg-sunken);
}
.fw-screen {
  position: relative;
  flex: 1;
  max-height: calc(100vh - 180px);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  overflow: hidden;
}
.float-win.maximized .fw-screen {
  max-height: calc(100vh - 120px);
  width: 100%;
}
.fw-screen img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.fw-screen-empty {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: center;
  color: var(--color-text-muted);
  padding: var(--sp-5);
}
.fw-error {
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: 8px;
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  background: var(--color-danger-weak);
  color: var(--color-danger);
  border: 1px solid color-mix(in srgb, var(--color-danger) 30%, transparent);
}
.fw-badge {
  position: absolute;
  right: 8px;
  top: 8px;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
}
.fw-rail {
  flex: none;
  width: 36px;
  padding: 4px 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-left: 1px solid var(--color-border);
  background: var(--color-bg-surface);
  overflow-y: auto;
}
.rail-btn {
  width: 30px;
  height: 28px;
  margin: 0 auto;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  display: grid;
  place-items: center;
}
.rail-btn:hover:not(:disabled) {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}
.rail-btn.danger {
  color: var(--color-danger);
}
.rail-btn.danger:hover:not(:disabled) {
  background: var(--color-danger-weak);
}
.rail-btn.disabled {
  opacity: 0.36;
  cursor: not-allowed;
}
.fw-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-top: 1px solid var(--color-border);
  color: var(--color-text-muted);
  background: var(--color-bg-surface);
}
.foot-meta {
  font-family: Consolas, monospace;
}
.foot-spacer {
  flex: 1;
}
.foot-link {
  border: none;
  background: transparent;
  color: var(--color-primary);
  font-size: 11px;
  cursor: pointer;
}
.fw-resize {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 14px;
  height: 14px;
  cursor: nwse-resize;
  background: linear-gradient(135deg, transparent 50%, var(--color-border-strong) 50%);
}
.dlg-tip {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-muted);
  line-height: 1.6;
}
.share-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid var(--color-border);
}
.shot-img {
  width: 100%;
  max-height: 60vh;
  object-fit: contain;
  background: var(--color-bg-sunken);
}
</style>
