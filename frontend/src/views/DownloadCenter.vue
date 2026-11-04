<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'

const auth = useAuth()
const canWrite = computed(() => auth.can('operator'))

const KIND_LABEL = {
  report_csv: '设备明细报表',
  screenshots: '批量截图',
  logcat: '设备日志',
}

const kind = ref('report_csv')
const deviceIds = ref([])
const lines = ref(200)
const creating = ref(false)

const tasks = ref([])
const devices = ref([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const r = await api.listDownloads({ limit: 100 })
    tasks.value = r.data || []
  } catch (e) {
    error.value = e?.response?.data?.detail || '加载下载任务失败，请重试'
  } finally {
    loading.value = false
  }
}

async function loadDevices() {
  try {
    const r = await api.listDevices()
    devices.value = r.data || []
  } catch {
    devices.value = []
  }
}

function onKindChange() {
  deviceIds.value = []
}

const NEED_DEVICE = computed(() => kind.value !== 'report_csv')

async function create() {
  if (NEED_DEVICE.value && !deviceIds.value.length) {
    ElMessage.warning('请先选择设备')
    return
  }
  creating.value = true
  try {
    const body = { kind: kind.value }
    if (NEED_DEVICE.value) body.device_ids = deviceIds.value
    if (kind.value === 'logcat') body.lines = lines.value
    const r = await api.createDownload(body)
    const task = r.data
    if (task.status === 'failed') {
      ElMessage.error(`生成失败：${task.error || '未知原因'}`)
    } else {
      ElMessage.success(`已生成「${task.filename}」，可在云盘下载或在此重下`)
    }
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '创建下载任务失败')
  } finally {
    creating.value = false
  }
}

async function download(row) {
  if (!row.cloud_file_id) return
  try {
    const r = await api.cloudDownload(row.cloud_file_id)
    const url = URL.createObjectURL(r.data)
    const a = document.createElement('a')
    a.href = url
    a.download = row.filename || `download-${row.id}`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '下载失败，文件可能已被清理')
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除任务「${row.title || row.filename || row.id}」？这会同时删除云盘中的生成文件，且不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await api.deleteDownload(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

function formatTime(v) {
  if (!v) return '—'
  return new Date(v).toLocaleString('zh-CN', { hour12: false })
}

function formatSize(n) {
  if (!n) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

onMounted(() => {
  load()
  loadDevices()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-select v-model="kind" style="width: 180px" @change="onKindChange">
        <el-option label="设备明细报表（CSV）" value="report_csv" />
        <el-option label="批量截图（ZIP）" value="screenshots" />
        <el-option label="设备日志（logcat）" value="logcat" />
      </el-select>
      <el-select
        v-if="NEED_DEVICE"
        v-model="deviceIds"
        multiple
        filterable
        collapse-tags
        collapse-tags-tooltip
        :max-collapse-tags="4"
        placeholder="选择设备（截图最多 30 台 / 日志最多 50 台）"
        style="min-width: 280px; flex: 1"
      >
        <el-option v-for="d in devices" :key="d.id" :label="`#${d.id} ${d.name}`" :value="d.id" />
      </el-select>
      <el-input-number v-if="kind === 'logcat'" v-model="lines" :min="10" :max="1000" :step="100" />
      <el-button type="primary" :loading="creating" :disabled="!canWrite" @click="create">
        生成并导入下载中心
      </el-button>
      <el-button :disabled="loading" @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="!canWrite"
      type="info"
      show-icon
      :closable="false"
      title="只读：当前角色不能创建或删除下载任务，仍可重新下载已有文件"
      class="readonly-hint"
    />

    <el-skeleton v-if="loading" :rows="5" animated class="state-box" />

    <el-alert v-else-if="error" type="error" show-icon :closable="false" :title="error" class="state-box">
      <template #default>
        <el-button size="small" @click="load">重试</el-button>
      </template>
    </el-alert>

    <el-empty v-else-if="!tasks.length" description="还没有下载任务" class="state-box">
      <p class="empty-guide">
        选择上方类型后点击「生成并导入下载中心」。生成物会落到云盘「我的文件」，
        可在此重新下载，也可在云盘页统一下发。
      </p>
    </el-empty>

    <el-table v-else :data="tasks" stripe size="small" class="task-table">
      <el-table-column label="时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ KIND_LABEL[row.kind] || row.kind }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="title" label="标题" min-width="140" show-overflow-tooltip />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'done' ? 'success' : 'danger'">
            {{ row.status === 'done' ? '完成' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="文件" min-width="220">
        <template #default="{ row }">
          <div v-if="row.status === 'done'" class="file-cell">
            <span class="fname">{{ row.filename }}</span>
            <span class="fsize">{{ formatSize(row.size_bytes) }}</span>
          </div>
          <span v-else class="err-text">{{ row.error || '生成失败' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="created_by" label="发起人" width="110" show-overflow-tooltip />
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            :disabled="!row.cloud_file_id"
            @click="download(row)"
          >重新下载</el-button>
          <el-button link type="danger" :disabled="!canWrite" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.readonly-hint {
  margin-bottom: var(--sp-3);
}
.state-box {
  padding: var(--sp-6) 0;
}
.empty-guide {
  margin-top: var(--sp-2);
  font-size: var(--font-sm);
  color: var(--color-text-muted);
}
.file-cell {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 0;
}
.fname {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fsize {
  flex: none;
  font-size: var(--font-xs);
  color: var(--color-text-muted);
}
.err-text {
  color: var(--color-danger);
  font-size: var(--font-xs);
}
.task-table {
  border-radius: var(--radius-md);
  overflow: hidden;
}
</style>
