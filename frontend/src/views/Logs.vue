<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../api/client'

const STATUS_META = {
  running: { label: '运行中', tag: 'success' },
  stopped: { label: '已停止', tag: 'info' },
  creating: { label: '创建中', tag: 'warning' },
  error: { label: '异常', tag: 'danger' },
}

const LINE_OPTIONS = [50, 100, 200, 500, 1000]

const devices = ref([])
const deviceId = ref(null)
const lines = ref(200)
const logLines = ref([])
const loading = ref(false)
const autoRefresh = ref(false)
const lastUpdated = ref(null)
const logBox = ref(null)
let timer = null

const currentDevice = computed(() => devices.value.find((d) => d.id === deviceId.value) || null)

async function loadDevices() {
  try {
    const { data } = await http.get('/devices')
    devices.value = data
    if (!deviceId.value && data.length) deviceId.value = data[0].id
  } catch (e) {
    ElMessage.error('设备列表获取失败')
  }
}

async function loadLogs() {
  if (!deviceId.value) return
  loading.value = true
  try {
    const { data } = await http.get(`/devices/${deviceId.value}/logcat`, {
      params: { lines: lines.value },
    })
    logLines.value = data.lines || []
    lastUpdated.value = new Date()
    // 滚动到底部（追加式日志，关注最新）
    requestAnimationFrame(() => {
      if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
    })
  } catch (e) {
    if (e?.response?.status === 404) {
      ElMessage.error('设备不存在')
    } else {
      ElMessage.error('日志获取失败')
    }
  } finally {
    loading.value = false
  }
}

function setupTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  if (autoRefresh.value) {
    timer = setInterval(loadLogs, 3000)
  }
}

watch(autoRefresh, setupTimer)
watch(deviceId, loadLogs)
watch(lines, loadLogs)

function statusMeta(k) {
  return STATUS_META[k] || { label: k, tag: 'info' }
}
function fmtTime(d) {
  return d ? d.toLocaleTimeString('zh-CN', { hour12: false }) : '—'
}

onMounted(async () => {
  await loadDevices()
  await loadLogs()
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="page logs">
    <div class="toolbar">
      <span style="font-weight: 600; font-size: 16px">设备日志</span>
      <div class="spacer" style="flex: 1"></div>

      <span class="muted">设备</span>
      <el-select v-model="deviceId" placeholder="选择设备" size="small" style="width: 200px" filterable>
        <el-option v-for="d in devices" :key="d.id" :label="`${d.name} (#${d.id})`" :value="d.id">
          <span>{{ d.name }}</span>
          <el-tag :type="statusMeta(d.status).tag" size="small" effect="plain" style="margin-left: 8px">
            {{ statusMeta(d.status).label }}
          </el-tag>
        </el-option>
      </el-select>

      <span class="muted">行数</span>
      <el-select v-model="lines" size="small" style="width: 100px">
        <el-option v-for="n in LINE_OPTIONS" :key="n" :label="n" :value="n" />
      </el-select>

      <el-switch v-model="autoRefresh" size="small" active-text="自动刷新" inline-prompt />
      <el-button :icon="'Refresh'" size="small" :loading="loading" @click="loadLogs">刷新</el-button>
    </div>

    <el-card shadow="never" body-style="padding: 0" class="log-card">
      <div class="log-head">
        <span>
          <el-tag v-if="currentDevice" :type="statusMeta(currentDevice.status).tag" size="small">
            {{ currentDevice.name }} · {{ statusMeta(currentDevice.status).label }}
          </el-tag>
          <span v-else class="muted">未选择设备</span>
        </span>
        <span class="muted">共 {{ logLines.length }} 行 · 更新 {{ fmtTime(lastUpdated) }}</span>
      </div>
      <pre ref="logBox" class="log-box" v-loading="loading">
<template v-if="logLines.length"><span v-for="(l, i) in logLines" :key="i" class="log-line">{{ l }}
</span></template><span v-else class="log-empty">暂无日志</span></pre>
    </el-card>
  </div>
</template>

<style scoped>
.logs {
  padding: 16px;
  display: flex;
  flex-direction: column;
  height: 100%;
  box-sizing: border-box;
}
.logs .toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.logs .muted {
  color: #86868b;
  font-size: 12px;
}
.log-card {
  border-radius: 12px;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.log-card :deep(.el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
}
.log-box {
  flex: 1;
  margin: 0;
  padding: 14px 16px;
  overflow: auto;
  background: #1c1c1e;
  color: #d1d1d6;
  font-family: 'SF Mono', 'Menlo', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  min-height: 360px;
}
.log-line {
  display: block;
}
.log-empty {
  color: #86868b;
}
</style>
