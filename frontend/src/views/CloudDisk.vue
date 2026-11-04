<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'
import { useDevices } from '../stores/devices'

const auth = useAuth()
const store = useDevices()

const files = ref([])
const usedBytes = ref(0)
const quotaBytes = ref(5 * 1024 * 1024 * 1024)
const category = ref('')
const keyword = ref('')
const loading = ref(false)
const uploading = ref(false)
const uploadPercent = ref(0)

const selectedIds = ref([])
const pushDlg = ref(false)
const pushFileIds = ref([])
const pushDeviceIds = ref([])
const remoteDir = ref('/sdcard/Download')
const job = ref(null)
const pushing = ref(false)
let pollTimer = null

const historyDlg = ref(false)
const historyLoading = ref(false)
const historyJobs = ref([])
const historyDetail = ref(null)
const JOB_STATUS = {
  running: { text: '进行中', type: 'warning' },
  done: { text: '已完成', type: 'success' },
  partial: { text: '部分失败', type: 'warning' },
  failed: { text: '失败', type: 'danger' },
  interrupted: { text: '已中断', type: 'info' },
}

const categories = [
  { key: '', label: '全部分类' },
  { key: 'image', label: '图片' },
  { key: 'video', label: '视频' },
  { key: 'apk', label: '安装包' },
  { key: 'document', label: '文档' },
  { key: 'other', label: '其他' },
]
const catLabel = (key) => categories.find((c) => c.key === key)?.label || key
const catType = { image: '', video: 'warning', apk: 'success', document: 'info', other: 'info' }

const usedText = computed(() => `${fmtSize(usedBytes.value)} / ${fmtSize(quotaBytes.value)}`)
const usedPercent = computed(() => Math.min(100, Math.round((usedBytes.value / quotaBytes.value) * 100)))

function fmtSize(n) {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

async function load() {
  loading.value = true
  try {
    const r = await api.cloudFiles({ category: category.value || undefined, q: keyword.value || undefined })
    files.value = r.data.files
    usedBytes.value = r.data.used_bytes
    quotaBytes.value = r.data.quota_bytes
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '云盘列表加载失败')
  } finally {
    loading.value = false
  }
}

async function onPick(uploadFile) {
  if (!auth.can('operator')) return ElMessage.warning('当前角色无权限')
  const raw = uploadFile.raw
  if (!raw) return
  if (raw.size > 200 * 1024 * 1024) {
    ElMessage.error('单个文件不能超过 200MB')
    return
  }
  uploading.value = true
  uploadPercent.value = 0
  try {
    await api.cloudUpload(raw, 'auto', (ev) => {
      if (ev.total) uploadPercent.value = Math.round((ev.loaded / ev.total) * 100)
    })
    ElMessage.success(`已上传：${raw.name}`)
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
    uploadPercent.value = 0
  }
}

async function download(row) {
  try {
    const r = await api.cloudDownload(row.id)
    const url = URL.createObjectURL(r.data)
    const a = document.createElement('a')
    a.href = url
    a.download = row.name
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '下载失败')
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确定删除云盘文件「${row.name}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await api.cloudDelete(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

function openPush(rows) {
  const ids = Array.isArray(rows) ? rows.map((r) => r.id) : [rows.id]
  pushFileIds.value = ids
  pushDeviceIds.value = []
  job.value = null
  pushDlg.value = true
  if (!store.list.length) store.refresh().catch(() => {})
}

function onSelection(rows) {
  selectedIds.value = rows.map((r) => r.id)
}

async function startPush() {
  if (!pushFileIds.value.length) return ElMessage.warning('请选择文件')
  if (!pushDeviceIds.value.length) return ElMessage.warning('请选择目标云机')
  if (!remoteDir.value.startsWith('/') || remoteDir.value.includes('..')) {
    return ElMessage.warning('远端目录必须是绝对路径且不含 ..')
  }
  pushing.value = true
  try {
    const r = await api.cloudPush({
      file_ids: pushFileIds.value,
      device_ids: pushDeviceIds.value,
      remote_dir: remoteDir.value,
    })
    job.value = { ...r.data, done: 0, failed: 0, items: [] }
    pollTimer = setInterval(poll, 700)
  } catch (e) {
    pushing.value = false
    ElMessage.error(e?.response?.data?.detail || '下发失败')
  }
}

async function poll() {
  if (!job.value?.job_id) return
  try {
    const r = await api.cloudPushStatus(job.value.job_id)
    job.value = r.data
    if (['done', 'partial', 'failed', 'interrupted'].includes(r.data.status)) {
      clearInterval(pollTimer)
      pollTimer = null
      pushing.value = false
      if (r.data.status === 'interrupted') ElMessage.warning('任务已中断（服务重启）')
      else if (r.data.failed) ElMessage.warning(`下发完成，${r.data.failed} 项失败`)
      else ElMessage.success('下发完成')
      load()
    }
  } catch (e) {
    clearInterval(pollTimer)
    pollTimer = null
    pushing.value = false
    ElMessage.error(e?.response?.data?.detail || '任务状态查询失败')
  }
}

async function openHistory() {
  historyDlg.value = true
  historyDetail.value = null
  historyLoading.value = true
  try {
    historyJobs.value = (await api.cloudPushJobs(30)).data.jobs
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '历史任务加载失败')
  } finally {
    historyLoading.value = false
  }
}

async function openJobDetail(row) {
  try {
    historyDetail.value = (await api.cloudPushStatus(row.id)).data
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '任务详情加载失败')
  }
}

async function togglePublic(row) {
  const next = !row.is_public
  try {
    await api.cloudSetPublic(row.id, next)
    ElMessage.success(next ? '已设为公共文件' : '已取消公共')
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '修改可见性失败')
  }
}

onMounted(() => {
  load()
  if (!store.list.length) store.refresh().catch(() => {})
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-select v-model="category" style="width: 140px" @change="load">
        <el-option v-for="c in categories" :key="c.key" :label="c.label" :value="c.key" />
      </el-select>
      <el-input v-model="keyword" placeholder="搜索文件名" clearable style="width: 220px" @keyup.enter="load" />
      <el-button @click="load">查询</el-button>
      <div style="flex: 1"></div>
      <el-upload
        v-if="auth.can('operator')"
        :auto-upload="false"
        :show-file-list="false"
        :on-change="onPick"
      >
        <el-button type="primary" :loading="uploading">上传文件</el-button>
      </el-upload>
      <el-button v-if="auth.can('operator')" :disabled="!selectedIds.length" @click="openPush(files.filter((f) => selectedIds.includes(f.id)))">
        批量下发（{{ selectedIds.length }}）
      </el-button>
      <el-button @click="openHistory">下发历史</el-button>
    </div>

    <el-progress v-if="uploading" :percentage="uploadPercent" :stroke-width="8" style="margin-bottom: 12px" />

    <div class="usage">
      <span>共享空间占用：{{ usedText }}</span>
      <el-progress :percentage="usedPercent" :stroke-width="6" style="flex: 1; margin-left: 12px" :show-text="false" />
    </div>

    <el-table v-loading="loading" :data="files" border stripe size="small" @selection-change="onSelection">
      <el-table-column type="selection" width="44" />
      <el-table-column label="文件名" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="fname">{{ row.name }}</span>
          <el-tag v-if="row.is_public" size="small" type="success" effect="plain" style="margin-left: 6px">公共</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="分类" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="catType[row.category]" effect="plain">{{ catLabel(row.category) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="100">
        <template #default="{ row }">{{ fmtSize(row.size_bytes) }}</template>
      </el-table-column>
      <el-table-column prop="uploaded_by" label="上传人" width="110" show-overflow-tooltip />
      <el-table-column label="上传时间" width="170">
        <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="download(row)">下载</el-button>
          <el-button v-if="auth.can('operator')" size="small" type="primary" plain @click="openPush(row)">传至云机</el-button>
          <el-button v-if="auth.can('admin')" size="small" plain @click="togglePublic(row)">
            {{ row.is_public ? '取消公共' : '设为公共' }}
          </el-button>
          <el-button v-if="auth.can('operator')" size="small" type="danger" plain @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="pushDlg" title="下发到云机" width="760px">
      <div class="push-files">
        <span>文件：</span>
        <el-tag v-for="fid in pushFileIds" :key="fid" size="small" effect="plain" style="margin-right: 6px">
          {{ files.find((f) => f.id === fid)?.name || `#${fid}` }}
        </el-tag>
      </div>
      <div class="push-dir">
        <span>远端目录：</span>
        <el-input v-model="remoteDir" style="width: 260px" placeholder="/sdcard/Download" />
      </div>
      <div class="push-hint">选择目标云机（simulator 下会直接成功，真机走 adb push）</div>
      <el-checkbox-group v-model="pushDeviceIds" class="device-picker">
        <el-checkbox v-for="d in store.list" :key="d.id" :value="d.id" :label="d.id" border>
          #{{ d.id }} {{ d.name }}
        </el-checkbox>
      </el-checkbox-group>

      <div v-if="job" class="job">
        <div class="job-line">
          <span>任务 {{ job.job_id.slice(0, 8) }} · {{ job.status }}</span>
          <span>成功 {{ job.done ?? 0 }} / 失败 {{ job.failed ?? 0 }} / 共 {{ job.total }}</span>
        </div>
        <el-progress
          :percentage="job.total ? Math.round((((job.done ?? 0) + (job.failed ?? 0)) / job.total) * 100) : 0"
          :status="job.failed ? 'warning' : 'success'"
        />
        <el-table v-if="job.items?.length" :data="job.items" size="small" max-height="220" style="margin-top: 8px">
          <el-table-column prop="device_name" label="云机" width="140" />
          <el-table-column prop="file_name" label="文件" min-width="160" show-overflow-tooltip />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="{ ok: 'success', failed: 'danger', pending: 'info' }[row.status]" effect="plain">
                {{ { ok: '成功', failed: '失败', pending: '等待' }[row.status] }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="error" label="错误" min-width="160" show-overflow-tooltip />
        </el-table>
      </div>

      <template #footer>
        <el-button @click="pushDlg = false">关闭</el-button>
        <el-button type="primary" :loading="pushing" :disabled="pushing" @click="startPush">开始下发</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="historyDlg" title="下发历史" width="820px">
      <el-table v-loading="historyLoading" :data="historyJobs" size="small" border max-height="360" empty-text="暂无下发记录">
        <el-table-column label="任务" width="110">
          <template #default="{ row }">{{ row.id.slice(0, 8) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="JOB_STATUS[row.status]?.type || 'info'" effect="plain">
              {{ JOB_STATUS[row.status]?.text || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="120">
          <template #default="{ row }">{{ row.done }} / {{ row.failed }} / {{ row.total }}</template>
        </el-table-column>
        <el-table-column prop="remote_dir" label="远端目录" min-width="150" show-overflow-tooltip />
        <el-table-column prop="created_by" label="发起人" width="110" />
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ row.created_at ? new Date(row.created_at).toLocaleString() : '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link @click="openJobDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="historyDetail" class="job" style="max-height: 260px; overflow: auto">
        <div class="job-line">
          <span>任务 {{ historyDetail.id.slice(0, 8) }} · {{ JOB_STATUS[historyDetail.status]?.text || historyDetail.status }}</span>
          <span>成功 {{ historyDetail.done }} / 失败 {{ historyDetail.failed }} / 共 {{ historyDetail.total }}</span>
        </div>
        <div v-if="historyDetail.error" class="push-hint">{{ historyDetail.error }}</div>
        <el-table :data="historyDetail.items" size="small" max-height="180">
          <el-table-column prop="device_name" label="云机" width="140" />
          <el-table-column prop="file_name" label="文件" min-width="150" show-overflow-tooltip />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="{ ok: 'success', failed: 'danger', pending: 'info' }[row.status]" effect="plain">
                {{ { ok: '成功', failed: '失败', pending: '等待' }[row.status] }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="error" label="错误" min-width="160" show-overflow-tooltip />
        </el-table>
      </div>

      <template #footer>
        <el-button @click="historyDlg = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.usage {
  display: flex;
  align-items: center;
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-bottom: 12px;
}
.fname {
  font-weight: 600;
}
.push-files,
.push-dir {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
  font-size: 13px;
  color: var(--color-text-secondary);
}
.push-hint {
  font-size: 12px;
  color: var(--color-text-muted);
  margin: 6px 0;
}
.device-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-height: 240px;
  overflow: auto;
}
.job {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px dashed var(--color-border);
}
.job-line {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
</style>
