<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useDevices } from '../stores/devices'
import { api } from '../api/client'
import PhoneFrame from '../components/PhoneFrame.vue'

defineOptions({ name: 'Grid' })

const store = useDevices()
const router = useRouter()
const cols = ref(3) // 2/3/4 -> 2x2 / 3x3 / 4x4
const groupId = ref('')

const shown = computed(() => {
  let list = store.list
    .filter((d) => !groupId.value || d.group_id === groupId.value)
  // 多控选中的设备始终留在视野内，切换分组后不会出现「选中了但看不到」
  if (selectedIds.value.length) {
    const ids = new Set(selectedIds.value)
    list = [...list].sort((a, b) => Number(ids.has(b.id)) - Number(ids.has(a.id)))
  }
  return list
})

// ---------- 多控（复用 /api/batch/*） ----------
const selectedIds = ref([])
const multiOpen = ref(false)
const mainId = ref(null)
const multiBusy = ref(false)
const multiResult = ref(null)
const multiError = ref('')
const lastOp = ref(null)

const selectedDevices = computed(() => shown.value.filter((d) => selectedIds.value.includes(d.id)))
const mainDevice = computed(() => shown.value.find((d) => d.id === mainId.value) || null)

function toggleSelect(d) {
  const i = selectedIds.value.indexOf(d.id)
  if (i >= 0) selectedIds.value.splice(i, 1)
  else selectedIds.value.push(d.id)
  multiResult.value = null
}

function openMulti() {
  if (selectedIds.value.length < 2) {
    ElMessage.warning('请先勾选至少 2 台设备，再进入多控模式')
    return
  }
  mainId.value = selectedIds.value[0]
  multiResult.value = null
  multiError.value = ''
  multiOpen.value = true
}

// 多控坐标：直接把主控设备的真实像素坐标 + 主控分辨率下发给后端，
// 后端 batch._scale 按目标设备实际分辨率折算（不再固定 1080×1920）。
// 主控分辨率取不到时（设备元数据缺失）才回落基准 1080×1920，并由后端记录日志。
const FALLBACK_W = 1080
const FALLBACK_H = 1920

function sourceDims(device) {
  const w = Number(device?.width) || 0
  const h = Number(device?.height) || 0
  if (w >= 200 && w <= 8192 && h >= 200 && h <= 8192) return { source_width: w, source_height: h }
  return { source_width: FALLBACK_W, source_height: FALLBACK_H }
}

async function broadcast(action, payload, idsOverride) {
  if (!selectedIds.value.length) return
  if (multiBusy.value) return
  multiBusy.value = true
  multiError.value = ''
  lastOp.value = { action, payload }
  try {
    const ids = idsOverride || [...selectedIds.value]
    const body = { device_ids: ids, ...payload }
    const { data } = await api.batch(action, body)
    multiResult.value = data
    if (data.failed) {
      ElMessage.warning(`多控完成：成功 ${data.ok} / ${data.total} 台，失败 ${data.failed} 台`)
    } else {
      ElMessage.success(`多控完成：${data.ok} / ${data.total} 台成功`)
    }
  } catch (e) {
    multiError.value = e?.response?.data?.detail || '多控下发失败'
    ElMessage.error(multiError.value)
  } finally {
    multiBusy.value = false
  }
}

function onMainTap(p) {
  if (!mainDevice.value) return
  broadcast('tap', { x: Math.round(p.x), y: Math.round(p.y), ...sourceDims(mainDevice.value) })
}

function onMainSwipe(p) {
  if (!mainDevice.value) return
  broadcast('swipe', {
    x1: Math.round(p.x1),
    y1: Math.round(p.y1),
    x2: Math.round(p.x2),
    y2: Math.round(p.y2),
    duration_ms: p.duration_ms,
    ...sourceDims(mainDevice.value),
  })
}

function onMainText(t) {
  if (!t) return
  broadcast('text', { text: t })
}

function onMainKey(key) {
  broadcast('key', { key })
}

function resultFor(id) {
  return (multiResult.value?.details || []).find((d) => d.device_id === id)
}

const failedIds = computed(() =>
  (multiResult.value?.details || []).filter((d) => !d.ok).map((d) => d.device_id),
)

async function retryFailedMulti() {
  if (!lastOp.value || !failedIds.value.length) return
  await broadcast(lastOp.value.action, lastOp.value.payload, failedIds.value)
}

function exportMultiResult() {
  const details = multiResult.value?.details || []
  if (!details.length) {
    ElMessage.warning('暂无多控结果可导出')
    return
  }
  const lines = ['设备ID,设备名,结果,失败原因']
  details.forEach((d) => {
    lines.push(`"${d.device_id}","${d.name || ''}","${d.ok ? '成功' : '失败'}","${(d.error || '').replace(/"/g, '""')}"`)
  })
  const blob = new Blob([`\ufeff${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `multi-control-${Date.now()}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// ---------- 单格全屏 ----------
const fsDevice = ref(null)
const fsShell = ref(null)

async function enterFullscreen(d) {
  fsDevice.value = d
  await nextTick()
  try {
    await fsShell.value?.requestFullscreen?.()
  } catch {
    /* 浏览器不支持/被拒绝时仍使用固定覆盖层，功能可用 */
  }
}

async function exitFullscreen() {
  if (document.fullscreenElement) {
    try {
      await document.exitFullscreen()
    } catch {
      /* 忽略：下面仍会关闭覆盖层 */
    }
  }
  fsDevice.value = null
}

function onFsChange() {
  if (!document.fullscreenElement && fsDevice.value) fsDevice.value = null
}

function onWindowKey(e) {
  if (e.key === 'Escape' && fsDevice.value && !document.fullscreenElement) {
    fsDevice.value = null
  }
}

async function singleTap(p) {
  if (!fsDevice.value) return
  try {
    await api.control(fsDevice.value.id, 'tap', p)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function singleSwipe(p) {
  if (!fsDevice.value) return
  try {
    await api.control(fsDevice.value.id, 'swipe', p)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function singleKey(key) {
  if (!fsDevice.value) return
  try {
    await api.control(fsDevice.value.id, 'key', { key })
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function singleText(text) {
  if (!fsDevice.value || !text) return
  try {
    await api.control(fsDevice.value.id, 'text', { text })
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

// ---------- 预览订阅 ----------
function resubscribe() {
  store.subscribePreviews(shown.value.map((d) => d.id), 1)
}

watch(shown, resubscribe)
watch(cols, resubscribe)

const isFirstLoad = ref(true)

onMounted(async () => {
  await store.refresh()
  await store.refreshGroups()
  resubscribe()
  isFirstLoad.value = false
  document.addEventListener('fullscreenchange', onFsChange)
  window.addEventListener('keydown', onWindowKey)
})

onActivated(() => {
  if (isFirstLoad.value) return
  store.refresh()
  store.refreshGroups()
  resubscribe()
})

onDeactivated(() => store.subscribePreviews([], 1))
onBeforeUnmount(() => {
  store.subscribePreviews([], 1)
  document.removeEventListener('fullscreenchange', onFsChange)
  window.removeEventListener('keydown', onWindowKey)
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span style="font-weight: 600">多画面实时预览</span>
      <el-radio-group v-model="cols">
        <el-radio-button :value="2">2 × 2</el-radio-button>
        <el-radio-button :value="3">3 × 3</el-radio-button>
        <el-radio-button :value="4">4 × 4</el-radio-button>
      </el-radio-group>
      <el-select v-model="groupId" placeholder="全部分组" clearable style="width: 150px">
        <el-option v-for="g in store.groups" :key="g.id" :label="g.name" :value="g.id" />
      </el-select>
      <el-button
        type="primary"
        plain
        :icon="'Operation'"
        :disabled="!selectedIds.length"
        @click="openMulti"
      >
        多控模式{{ selectedIds.length ? ` (${selectedIds.length})` : '' }}
      </el-button>
      <div class="spacer"></div>
      <el-tag type="info">共 {{ shown.length }} 台 · 勾选后可 1 控 N，点击画面进入单机</el-tag>
    </div>

    <div class="grid" :style="{ gridTemplateColumns: `repeat(${cols}, 1fr)` }">
      <div v-for="d in shown" :key="d.id" class="cell">
        <PhoneFrame
          :device="d"
          :frame="store.frames[d.id]"
          selectable
          :selected="selectedIds.includes(d.id)"
          @open="router.push(`/device/${d.id}?from=grid`)"
          @toggle="toggleSelect"
        />
        <button class="fs-btn" title="单格全屏" @click.stop="enterFullscreen(d)">⛶</button>
      </div>
    </div>
    <el-empty v-if="!shown.length" description="暂无设备，请先到「设备管理」批量建机" />

    <!-- 多控面板 -->
    <el-dialog v-model="multiOpen" title="多控模式（1 控 N）" width="820px" top="4vh">
      <template v-if="mainDevice">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="主控画面上的点击/滑动/按键会广播到全部已选设备；坐标按各设备分辨率自动折算。"
        />
        <div class="mc-bar">
          <span class="mc-label">主控</span>
          <el-select v-model="mainId" size="small" style="width: 240px">
            <el-option
              v-for="d in selectedDevices"
              :key="d.id"
              :label="`#${d.id} ${d.name}`"
              :value="d.id"
            />
          </el-select>
          <span class="mc-targets">目标 {{ selectedIds.length }} 台</span>
          <div class="spacer"></div>
          <el-tag v-if="multiBusy" type="warning">下发中…</el-tag>
          <el-tag v-else-if="multiResult" :type="multiResult.failed ? 'warning' : 'success'">
            {{ multiResult.failed ? '部分成功' : '全部成功' }} · {{ multiResult.ok }}/{{ multiResult.total }}
          </el-tag>
          <el-button v-if="multiResult" size="small" plain @click="exportMultiResult">导出结果</el-button>
          <el-button
            v-if="failedIds.length"
            size="small"
            type="warning"
            :disabled="multiBusy"
            @click="retryFailedMulti"
          >重试失败 {{ failedIds.length }}</el-button>
        </div>

        <div class="mc-layout">
          <div class="mc-screen">
            <PhoneFrame
              :device="mainDevice"
              :frame="store.frames[mainId]"
              :style="{ aspectRatio: `${mainDevice.width} / ${mainDevice.height}` }"
              clickable
              swipeable
              typeable
              @open="() => {}"
              @tap="onMainTap"
              @swipe="onMainSwipe"
              @text="onMainText"
              @key="onMainKey"
            />
          </div>
          <div class="mc-side">
            <div class="mc-keys">
              <el-button size="small" :disabled="multiBusy" @mousedown.prevent="onMainKey('back')">返回</el-button>
              <el-button size="small" :disabled="multiBusy" @mousedown.prevent="onMainKey('home')">主页</el-button>
              <el-button size="small" :disabled="multiBusy" @mousedown.prevent="onMainKey('recent')">任务</el-button>
              <el-button size="small" :disabled="multiBusy" @mousedown.prevent="onMainKey('power')">电源</el-button>
            </div>
            <el-alert v-if="multiError" type="error" :closable="false" show-icon :title="multiError" />
            <div class="mc-list">
              <div v-for="d in selectedDevices" :key="d.id" class="mc-item">
                <span class="mono">#{{ d.id }}</span>
                <span class="mc-name">{{ d.name }}</span>
                <el-tag
                  v-if="resultFor(d.id)"
                  size="small"
                  :type="resultFor(d.id).ok ? 'success' : 'danger'"
                >{{ resultFor(d.id).ok ? '成功' : '失败' }}</el-tag>
                <el-tooltip v-if="resultFor(d.id)?.error" :content="resultFor(d.id).error" placement="top">
                  <span class="mc-err">原因</span>
                </el-tooltip>
                <el-tag v-else size="small" type="info" effect="plain">待下发</el-tag>
              </div>
            </div>
          </div>
        </div>
      </template>
      <el-empty v-else description="主控设备已被移除，请重新选择" />
      <template #footer>
        <el-button @click="multiOpen = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 单格全屏（控制条固定在顶部独立一行，不遮挡画面） -->
    <div v-if="fsDevice" ref="fsShell" class="fs-shell">
      <div class="fs-bar">
        <span class="fs-name">#{{ fsDevice.id }} {{ fsDevice.name }}</span>
        <el-button size="small" @click="singleKey('back')">返回</el-button>
        <el-button size="small" @click="singleKey('home')">主页</el-button>
        <el-button size="small" @click="singleKey('recent')">任务</el-button>
        <div class="spacer"></div>
        <el-button size="small" type="primary" @click="exitFullscreen">退出全屏 (Esc)</el-button>
      </div>
      <div class="fs-body">
        <PhoneFrame
          :device="fsDevice"
          :frame="store.frames[fsDevice.id]"
          :style="{ aspectRatio: `${fsDevice.width} / ${fsDevice.height}` }"
          clickable
          swipeable
          typeable
          @open="() => {}"
          @tap="singleTap"
          @swipe="singleSwipe"
          @text="singleText"
          @key="singleKey"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.cell {
  position: relative;
}
.fs-btn {
  position: absolute;
  top: var(--sp-2);
  right: var(--sp-2);
  z-index: var(--z-sticky);
  border: none;
  border-radius: var(--radius-sm);
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: var(--font-md);
  line-height: 1;
  padding: var(--sp-1) var(--sp-2);
  cursor: pointer;
  opacity: 0;
  transition: opacity var(--ease-fast);
}
.cell:hover .fs-btn {
  opacity: 1;
}
.fs-btn:hover {
  background: rgba(0, 0, 0, 0.8);
}

.mc-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin: var(--sp-3) 0;
}
.mc-label {
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}
.mc-targets {
  font-size: var(--font-xs);
  color: var(--color-text-muted);
}
.mc-layout {
  display: flex;
  gap: var(--sp-4);
  align-items: flex-start;
}
.mc-screen {
  width: 320px;
  flex: none;
}
.mc-screen :deep(.phone) {
  width: 100%;
}
.mc-side {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.mc-keys {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}
.mc-keys :deep(.el-button + .el-button) {
  margin-left: 0;
}
.mc-list {
  max-height: 300px;
  overflow: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}
.mc-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--color-border);
  font-size: var(--font-xs);
}
.mc-item:last-child {
  border-bottom: none;
}
.mc-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mc-err {
  color: var(--color-danger);
  cursor: help;
}

.fs-shell {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: flex;
  flex-direction: column;
  background: #000;
}
.fs-bar {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-4);
  background: var(--color-bg-surface);
  border-bottom: 1px solid var(--color-border);
}
.fs-name {
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--color-text-primary);
  margin-right: var(--sp-2);
}
.fs-body {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-3);
  overflow: hidden;
}
.fs-body :deep(.phone) {
  height: 100%;
  width: auto;
  max-width: 100%;
  max-height: 100%;
  flex: none;
}
</style>
