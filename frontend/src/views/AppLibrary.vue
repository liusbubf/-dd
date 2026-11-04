<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'
import { useDevices } from '../stores/devices'

defineOptions({ name: 'AppLibrary' })

const auth = useAuth()
const store = useDevices()
const router = useRouter()

const files = ref([])
const loading = ref(false)
const error = ref('')
const q = ref('')
const used = ref(0)
const quota = ref(0)
const uploadPct = ref(null)
const uploading = ref(false)

const canWrite = computed(() => auth.can('operator'))
const canAdmin = computed(() => auth.can('admin'))
const quotaText = computed(() => {
  if (!quota.value) return ''
  return `已用 ${fmtSize(used.value)} / ${fmtSize(quota.value)}`
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.cloudFiles({ category: 'apk', q: q.value || undefined })
    files.value = data.files || []
    used.value = data.used_bytes || 0
    quota.value = data.quota_bytes || 0
  } catch (e) {
    error.value = e?.response?.data?.detail || '安装包列表加载失败'
  } finally {
    loading.value = false
  }
}

function fmtSize(n) {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`
}

function fmtTime(t) {
  return t ? new Date(t).toLocaleString() : '—'
}

async function onUpload(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (!file) return
  if (!/\.(apk|xapk)$/i.test(file.name)) {
    ElMessage.warning('应用库只接收 APK 文件')
    return
  }
  uploading.value = true
  uploadPct.value = 0
  try {
    await api.cloudUpload(file, 'apk', (e) => {
      if (e.total) uploadPct.value = Math.round((e.loaded / e.total) * 100)
    })
    ElMessage.success(`已上传 ${file.name}`)
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
    uploadPct.value = null
  }
}

async function togglePublic(f) {
  try {
    await api.cloudSetPublic(f.id, !f.is_public)
    ElMessage.success(f.is_public ? '已设为私有' : '已设为公共')
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function removeFile(f) {
  try {
    await ElMessageBox.confirm(`确定删除安装包「${f.name}」？删除后已派发的任务不受影响。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
    })
  } catch {
    return
  }
  try {
    await api.cloudDelete(f.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

async function download(f) {
  try {
    const { data } = await api.cloudDownload(f.id)
    const url = URL.createObjectURL(data)
    const a = document.createElement('a')
    a.href = url
    a.download = f.name
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '下载失败')
  }
}

// ---- 推送 ----
const pushDlg = ref(false)
const pushFile = ref(null)
const pushDeviceIds = ref([])
const remoteDir = ref('/sdcard/Download')
const pushing = ref(false)

function openPush(f) {
  pushFile.value = f
  pushDeviceIds.value = []
  remoteDir.value = '/sdcard/Download'
  pushDlg.value = true
}

async function submitPush() {
  if (!pushDeviceIds.value.length) {
    ElMessage.warning('请选择至少一台设备')
    return
  }
  pushing.value = true
  try {
    const { data } = await api.cloudPush({
      file_ids: [pushFile.value.id],
      device_ids: pushDeviceIds.value,
      remote_dir: remoteDir.value || '/sdcard/Download',
    })
    ElMessage.success(`已创建推送任务（${data.total} 个设备项），可在推送进度页查看`)
    pushDlg.value = false
    router.push({ path: '/push-jobs', query: { job: data.job_id } })
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '推送失败')
  } finally {
    pushing.value = false
  }
}

onMounted(() => {
  load()
  if (!store.list.length) store.refresh().catch(() => {})
})
onActivated(() => load())
onDeactivated(() => {})
onBeforeUnmount(() => {})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span class="page-title">应用库 · 公共安装包</span>
      <el-input v-model="q" placeholder="搜索安装包" clearable style="width: 200px" @keyup.enter="load" @clear="load" />
      <el-button @click="load">刷新</el-button>
      <div class="spacer"></div>
      <span class="quota">{{ quotaText }}</span>
      <el-upload
        v-if="canWrite"
        :show-file-list="false"
        :auto-upload="false"
        accept=".apk,.xapk"
        @change="onUpload"
      >
        <el-button type="primary" :loading="uploading">上传 APK</el-button>
      </el-upload>
    </div>

    <el-alert
      v-if="!canWrite"
      type="info"
      show-icon
      :closable="false"
      title="当前角色为只读：可以浏览、下载安装包，但上传/推送/删除需要操作员及以上权限。"
    />

    <div v-if="uploading" class="upload-bar">
      <span>上传中… {{ uploadPct ?? 0 }}%</span>
      <el-progress :percentage="uploadPct ?? 0" :show-text="false" />
    </div>

    <div v-if="loading" class="state-box">
      <el-icon class="is-loading" :size="26"><Loading /></el-icon>
      <p>正在加载安装包…</p>
    </div>
    <div v-else-if="error" class="state-box">
      <p class="state-title">加载失败</p>
      <p class="state-sub">{{ error }}</p>
      <el-button size="small" type="primary" @click="load">重试</el-button>
    </div>
    <el-empty v-else-if="!files.length" description="应用库还是空的，上传第一个 APK 试试" />

    <el-table v-else :data="files" border size="small" style="width: 100%">
      <el-table-column prop="name" label="安装包" min-width="220" show-overflow-tooltip />
      <el-table-column label="大小" width="100">
        <template #default="{ row }">{{ fmtSize(row.size_bytes) }}</template>
      </el-table-column>
      <el-table-column label="归属" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="row.is_public ? 'success' : 'info'" effect="plain">
            {{ row.is_public ? '公共' : '私有' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="uploaded_by" label="上传人" width="120" />
      <el-table-column label="上传时间" width="170">
        <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="300" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="download(row)">下载</el-button>
          <el-button size="small" type="primary" :disabled="!canWrite" @click="openPush(row)">推送</el-button>
          <el-button v-if="canAdmin" size="small" plain @click="togglePublic(row)">
            {{ row.is_public ? '设为私有' : '设为公共' }}
          </el-button>
          <el-button v-if="canWrite" size="small" type="danger" @click="removeFile(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="pushDlg" title="推送安装包" width="520px">
      <el-form label-width="90px">
        <el-form-item label="安装包">
          <span class="mono">{{ pushFile?.name }}</span>
        </el-form-item>
        <el-form-item label="目标设备">
          <el-select
            v-model="pushDeviceIds"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择设备（可多选）"
            style="width: 100%"
          >
            <el-option
              v-for="d in store.list"
              :key="d.id"
              :label="`#${d.id} ${d.name}（${d.status}）`"
              :value="d.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="远端目录">
          <el-input v-model="remoteDir" placeholder="/sdcard/Download" />
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="串行下发，避免同时开多个 adb；逐设备进度与失败原因在「推送进度」页查看。"
      />
      <template #footer>
        <el-button @click="pushDlg = false">取消</el-button>
        <el-button type="primary" :loading="pushing" :disabled="!pushDeviceIds.length" @click="submitPush">
          推送到 {{ pushDeviceIds.length }} 台设备
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-title {
  font-weight: 600;
  color: var(--color-text-primary);
}
.quota {
  margin-right: var(--sp-3);
  font-size: var(--font-xs);
  color: var(--color-text-muted);
}
.upload-bar {
  margin: var(--sp-3) 0;
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}
.state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  min-height: 200px;
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
.mono {
  font-family: var(--font-mono, monospace);
  font-size: var(--font-sm);
}
</style>
