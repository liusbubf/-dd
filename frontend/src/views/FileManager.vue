<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http, { api } from '../api/client'
import { useAuth } from '../stores/auth'

const auth = useAuth()
const ROOT = '/sdcard/'

const devices = ref([])
const deviceId = ref(null)
const path = ref(ROOT)
const items = ref([])
const loading = ref(false)
const uploading = ref(false)
const fileInput = ref(null)

// 目录排在前、文件在后，各自按名称排序，浏览更顺手
const sortedItems = computed(() =>
  [...items.value].sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
    return a.name.localeCompare(b.name)
  }),
)

// 已在根目录（/sdcard/ 或 /）时不允许再往上
const canUp = computed(() => {
  const p = path.value.replace(/\/+$/, '')
  return p !== '' && path.value !== ROOT
})

function joinPath(dir, name) {
  return dir.replace(/\/+$/, '') + '/' + name
}

async function loadDevices() {
  try {
    const { data } = await api.listDevices()
    devices.value = data || []
    if (!deviceId.value && devices.value.length) {
      deviceId.value = devices.value[0].id
      await loadFiles()
    }
  } catch {
    ElMessage.error('设备列表获取失败')
  }
}

async function loadFiles() {
  if (deviceId.value == null) return
  loading.value = true
  try {
    const { data } = await http.get(`/devices/${deviceId.value}/files`, {
      params: { path: path.value },
    })
    items.value = data.items || []
  } catch (e) {
    items.value = []
    ElMessage.error(e?.response?.data?.detail || '目录读取失败')
  } finally {
    loading.value = false
  }
}

function onDeviceChange() {
  path.value = ROOT
  loadFiles()
}

function enter(item) {
  if (!item.is_dir) return
  path.value = joinPath(path.value, item.name) + '/'
  loadFiles()
}

function goUp() {
  if (!canUp.value) return
  const p = path.value.replace(/\/+$/, '')
  const idx = p.lastIndexOf('/')
  path.value = idx <= 0 ? '/' : p.slice(0, idx + 1)
  loadFiles()
}

function goHome() {
  path.value = ROOT
  loadFiles()
}

function triggerUpload() {
  if (deviceId.value == null) {
    ElMessage.warning('请先选择设备')
    return
  }
  fileInput.value?.click()
}

async function onFilePicked(e) {
  const f = e.target.files?.[0]
  if (!f) return
  const fd = new FormData()
  fd.append('file', f)
  fd.append('remote_dir', path.value)
  uploading.value = true
  try {
    await http.post(`/devices/${deviceId.value}/files/upload`, fd)
    ElMessage.success(`已上传 ${f.name}`)
    loadFiles()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
    e.target.value = '' // 重置以便同名文件可再次选择
  }
}

async function download(item) {
  const remote = joinPath(path.value, item.name)
  try {
    const { data } = await http.get(`/devices/${deviceId.value}/files/download`, {
      params: { path: remote },
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([data]))
    const a = document.createElement('a')
    a.href = url
    a.download = item.name
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
    ElMessage.success(`已下载 ${item.name}`)
  } catch {
    ElMessage.error('下载失败')
  }
}

async function remove(item) {
  const remote = joinPath(path.value, item.name)
  try {
    await ElMessageBox.confirm(`确认删除「${item.name}」？此操作不可恢复。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    await http.delete(`/devices/${deviceId.value}/files`, { params: { path: remote } })
    ElMessage.success('已删除')
    loadFiles()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '删除失败')
  }
}

onMounted(loadDevices)
</script>

<template>
  <div class="page file-manager">
    <div class="toolbar">
      <span style="font-weight: 600; font-size: 16px">文件互传</span>
      <el-select
        v-model="deviceId"
        placeholder="选择设备"
        size="small"
        style="width: 220px"
        filterable
        @change="onDeviceChange"
      >
        <el-option v-for="d in devices" :key="d.id" :label="d.name" :value="d.id" />
      </el-select>
      <div style="flex: 1"></div>
      <el-button v-if="auth.can('operator')" :icon="'Upload'" type="primary" size="small" :loading="uploading" @click="triggerUpload">
        上传文件
      </el-button>
      <el-button :icon="'Refresh'" size="small" :loading="loading" @click="loadFiles">刷新</el-button>
      <input ref="fileInput" type="file" style="display: none" @change="onFilePicked" />
    </div>

    <!-- 路径栏 -->
    <div class="pathbar">
      <el-button :icon="'HomeFilled'" size="small" text @click="goHome">根目录</el-button>
      <el-button :icon="'Top'" size="small" text :disabled="!canUp" @click="goUp">上级目录</el-button>
      <el-tag type="info" effect="plain" style="font-family: monospace">{{ path }}</el-tag>
    </div>

    <el-table
      v-loading="loading"
      :data="sortedItems"
      border
      stripe
      size="small"
      style="width: 100%"
      empty-text="该目录为空"
    >
      <el-table-column label="名称" min-width="280">
        <template #default="{ row }">
          <span
            :class="{ 'dir-name': row.is_dir }"
            :style="row.is_dir ? 'cursor:pointer' : ''"
            @click="enter(row)"
          >
            <el-icon style="vertical-align: -2px; margin-right: 6px">
              <component :is="row.is_dir ? 'Folder' : 'Document'" />
            </el-icon>
            {{ row.name }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag :type="row.is_dir ? 'warning' : 'info'" size="small" effect="light">
            {{ row.is_dir ? '目录' : '文件' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" align="right">
        <template #default="{ row }">
          <template v-if="row.is_dir">
            <el-button size="small" text type="primary" @click="enter(row)">进入</el-button>
          </template>
          <template v-else>
            <el-button size="small" text type="primary" @click="download(row)">下载</el-button>
          </template>
          <el-button v-if="auth.can('operator')" size="small" text type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.file-manager {
  padding: 16px;
}
.file-manager .toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.file-manager .pathbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.dir-name {
  color: #007aff;
  font-weight: 500;
}
</style>
