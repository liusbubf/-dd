<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'

defineOptions({ name: 'PushProgress' })

const auth = useAuth()
const route = useRoute()

const jobs = ref([])
const loading = ref(false)
const error = ref('')
const detail = ref(null)
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const retrying = ref(false)

let timer = null

const canWrite = computed(() => auth.can('operator'))

const STATUS = {
  running: { text: '进行中', type: 'warning' },
  done: { text: '全部成功', type: 'success' },
  partial: { text: '部分成功', type: 'warning' },
  failed: { text: '失败', type: 'danger' },
  interrupted: { text: '已中断', type: 'info' },
}
function statusOf(s) {
  return STATUS[s] || { text: s || '未知', type: 'info' }
}

function pct(job) {
  if (!job.total) return 0
  return Math.round(((job.done + job.failed) / job.total) * 100)
}

function fmtTime(t) {
  return t ? new Date(t).toLocaleString() : '—'
}

async function load(showLoading = true) {
  if (showLoading) loading.value = true
  error.value = ''
  try {
    const { data } = await api.cloudPushJobs(50)
    jobs.value = data.jobs || []
  } catch (e) {
    error.value = e?.response?.data?.detail || '推送任务加载失败'
  } finally {
    loading.value = false
    schedule()
  }
}

function schedule() {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  if (!jobs.value.some((j) => j.status === 'running')) return
  timer = setTimeout(() => {
    load(false)
    if (detailOpen.value && detail.value?.status === 'running') loadDetail(detail.value.id, false)
  }, 2500)
}

async function openDetail(id) {
  detailOpen.value = true
  await loadDetail(id)
}

async function loadDetail(id, showLoading = true) {
  if (showLoading) detailLoading.value = true
  detailError.value = ''
  try {
    const { data } = await api.cloudPushStatus(id)
    detail.value = data
  } catch (e) {
    detailError.value = e?.response?.data?.detail || '任务详情加载失败'
  } finally {
    detailLoading.value = false
  }
}

async function retryFailed() {
  if (!detail.value) return
  retrying.value = true
  try {
    const { data } = await api.cloudRetryPush(detail.value.id)
    ElMessage.success(`已创建重试任务（${data.total} 个失败项）`)
    detailOpen.value = false
    await load(false)
    openDetail(data.job_id)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '重试失败')
  } finally {
    retrying.value = false
  }
}

function exportCsv() {
  const items = detail.value?.items || []
  if (!items.length) {
    ElMessage.warning('该任务没有可导出的明细')
    return
  }
  const head = ['设备ID', '设备名称', '文件ID', '文件名', '状态', '失败原因']
  const lines = [head.join(',')]
  items.forEach((i) => {
    const row = [
      i.device_id,
      i.device_name,
      i.file_id,
      i.file_name,
      i.status === 'ok' ? '成功' : i.status === 'failed' ? '失败' : '待处理',
      (i.error || '').replace(/"/g, '""'),
    ]
    lines.push(row.map((v) => `"${v}"`).join(','))
  })
  const blob = new Blob([`\ufeff${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `push-${detail.value.id.slice(0, 8)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(async () => {
  await load()
  if (route.query.job) openDetail(String(route.query.job))
})
onActivated(() => load(false))
onDeactivated(() => {
  if (timer) clearTimeout(timer)
})
onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span class="page-title">推送进度</span>
      <el-tag v-if="jobs.some((j) => j.status === 'running')" type="warning" size="small">
        有任务进行中，自动刷新中…
      </el-tag>
      <div class="spacer"></div>
      <el-button @click="load()">刷新</el-button>
    </div>

    <el-alert
      v-if="!canWrite"
      type="info"
      show-icon
      :closable="false"
      title="只读角色：可查看自己发起的任务明细，失败重试需要操作员及以上权限。"
    />

    <div v-if="loading" class="state-box">
      <el-icon class="is-loading" :size="26"><Loading /></el-icon>
      <p>正在加载推送任务…</p>
    </div>
    <div v-else-if="error" class="state-box">
      <p class="state-title">加载失败</p>
      <p class="state-sub">{{ error }}</p>
      <el-button size="small" type="primary" @click="load()">重试</el-button>
    </div>
    <el-empty v-else-if="!jobs.length" description="还没有推送任务，去「应用库」选择安装包推送" />

    <el-table v-else :data="jobs" border size="small" style="width: 100%">
      <el-table-column label="任务" width="150">
        <template #default="{ row }"><span class="mono">{{ row.id.slice(0, 10) }}</span></template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="statusOf(row.status).type">{{ statusOf(row.status).text }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="进度" min-width="180">
        <template #default="{ row }">
          <el-progress :percentage="pct(row)" :status="row.status === 'failed' ? 'exception' : undefined" :stroke-width="10" />
          <span class="sub">成功 {{ row.done }} · 失败 {{ row.failed }} · 共 {{ row.total }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="remote_dir" label="远端目录" min-width="150" show-overflow-tooltip />
      <el-table-column prop="created_by" label="发起人" width="110" />
      <el-table-column label="创建时间" width="170">
        <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" plain @click="openDetail(row.id)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="detailOpen" title="推送任务详情" size="720px">
      <div v-if="detailLoading" class="state-box">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
        <p>正在加载明细…</p>
      </div>
      <div v-else-if="detailError" class="state-box">
        <p class="state-title">加载失败</p>
        <p class="state-sub">{{ detailError }}</p>
        <el-button size="small" type="primary" @click="loadDetail(detail?.id)">重试</el-button>
      </div>
      <template v-else-if="detail">
        <div class="detail-head">
          <el-tag :type="statusOf(detail.status).type">{{ statusOf(detail.status).text }}</el-tag>
          <span class="sub">成功 {{ detail.done }} / 失败 {{ detail.failed }} / 共 {{ detail.total }}</span>
          <div class="spacer"></div>
          <el-button size="small" @click="exportCsv">导出 CSV</el-button>
          <el-button
            v-if="detail.failed > 0 && canWrite"
            size="small"
            type="warning"
            :loading="retrying"
            @click="retryFailed"
          >
            重试失败项（{{ detail.failed }}）
          </el-button>
        </div>
        <el-table :data="detail.items || []" border size="small" max-height="520">
          <el-table-column prop="device_id" label="设备 ID" width="80" />
          <el-table-column prop="device_name" label="设备名" width="140" show-overflow-tooltip />
          <el-table-column prop="file_name" label="文件" min-width="160" show-overflow-tooltip />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.status === 'ok' ? 'success' : row.status === 'failed' ? 'danger' : 'info'"
              >{{ row.status === 'ok' ? '成功' : row.status === 'failed' ? '失败' : '待处理' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="error" label="失败原因" min-width="200" show-overflow-tooltip />
        </el-table>
        <p v-if="!detail.failed && detail.status !== 'running'" class="sub">该任务没有失败项。</p>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.page-title {
  font-weight: 600;
  color: var(--color-text-primary);
}
.state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  min-height: 180px;
  color: var(--color-text-muted);
  font-size: var(--font-sm);
}
.state-title {
  color: var(--color-danger);
  font-weight: 600;
}
.state-sub {
  max-width: 420px;
  text-align: center;
}
.sub {
  font-size: var(--font-xs);
  color: var(--color-text-muted);
}
.detail-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin-bottom: var(--sp-3);
}
.mono {
  font-family: var(--font-mono, monospace);
}
</style>
