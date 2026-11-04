<script setup>
import { onMounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/client'
import { useAuth } from '../stores/auth'
import { api } from '../api/client'
import { useDevices } from '../stores/devices'

const store = useDevices()
const auth = useAuth()

// —— 单机应用管理 ——
const curDeviceId = ref(null)
const apps = ref([])
const loadingApps = ref(false)
const rowBusy = ref('') // 正在操作的「包名+动作」标记，用于按钮 loading

const appRows = computed(() => apps.value.map((p, i) => ({ i: i + 1, pkg: p })))

async function loadApps() {
  if (!curDeviceId.value) {
    apps.value = []
    return
  }
  loadingApps.value = true
  try {
    const { data } = await http.get(`/devices/${curDeviceId.value}/apps`)
    apps.value = data.apps || []
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载已装应用失败')
  } finally {
    loadingApps.value = false
  }
}

async function appAction(action, pkg, label, needConfirm) {
  if (needConfirm) {
    try {
      await ElMessageBox.confirm(`确认对「${pkg}」执行「${label}」？`, '确认操作', {
        type: 'warning',
        confirmButtonText: '确定',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
  }
  rowBusy.value = `${pkg}:${action}`
  try {
    await http.post(`/devices/${curDeviceId.value}/apps/${action}`, { package: pkg })
    ElMessage.success(`${label}成功`)
    if (action === 'uninstall') await loadApps()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || `${label}失败`)
  } finally {
    rowBusy.value = ''
  }
}

// —— 批量应用管理 ——
const batchSelected = ref([]) // 选中的设备行
const batchPkg = ref('')
const batchApk = ref('https://example.com/app.apk')

const batchIds = computed(() => batchSelected.value.map((d) => d.id))
const lastResult = ref(null) // {label, ok, failed, total}

function onBatchSelect(rows) {
  batchSelected.value = rows
}

async function batchRun(action, label, payload, needConfirm) {
  if (!batchIds.value.length) return ElMessage.warning('请先勾选设备')
  if (needConfirm) {
    try {
      await ElMessageBox.confirm(
        `确认对已选 ${batchIds.value.length} 台设备执行「${label}」？`,
        '批量操作确认',
        { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  lastResult.value = null
  store.batchProgress = { action, done: 0, total: batchIds.value.length }
  try {
    const { data } = await http.post(`/apps/batch/${action}`, {
      device_ids: batchIds.value,
      ...payload,
    })
    store.batchProgress = { action, done: data.total, total: data.total }
    lastResult.value = { label, ok: data.ok, failed: data.failed, total: data.total }
    ElMessage.success(`${label}：成功 ${data.ok}/${data.total}`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '批量操作失败')
  }
}

function batchAppAction(action, label, needConfirm) {
  if (!batchPkg.value) return ElMessage.warning('请输入包名')
  return batchRun(action, label, { package: batchPkg.value }, needConfirm)
}

function batchInstall() {
  if (!batchApk.value) return ElMessage.warning('请输入 APK URL')
  return batchRun('install', '批量安装', { apk_url: batchApk.value }, false)
}

const progressPct = computed(() => {
  const p = store.batchProgress
  return p && p.total ? Math.round((p.done / p.total) * 100) : 0
})

const statusText = { running: '运行中', stopped: '已停止', creating: '创建中', error: '异常' }
const statusType = { running: 'success', stopped: 'info', creating: 'warning', error: 'danger' }

onMounted(async () => {
  await store.refresh()
  if (store.list.length && !curDeviceId.value) {
    curDeviceId.value = store.list[0].id
    await loadApps()
  }
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-icon><Box /></el-icon>
      <span style="font-weight: 600">应用管理</span>
      <div class="spacer"></div>
      <el-button :icon="'Refresh'" @click="store.refresh()">刷新设备</el-button>
    </div>

    <!-- ① 单机应用管理 -->
    <el-card shadow="never" style="margin-bottom: 14px">
      <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px">
        <span style="font-weight: 600">① 单机应用管理</span>
        <el-select
          v-model="curDeviceId"
          placeholder="选择设备"
          filterable
          style="width: 220px"
          @change="loadApps"
        >
          <el-option
            v-for="d in store.list"
            :key="d.id"
            :label="`${d.name}（${statusText[d.status] || d.status}）`"
            :value="d.id"
          />
        </el-select>
        <el-button :icon="'Refresh'" :disabled="!curDeviceId" @click="loadApps">刷新应用</el-button>
        <el-tag type="info">共 {{ apps.length }} 个</el-tag>
      </div>

      <el-table
        v-loading="loadingApps"
        :data="appRows"
        border
        stripe
        size="small"
        max-height="420"
      >
        <el-table-column prop="i" label="#" width="60" />
        <el-table-column prop="pkg" label="包名" min-width="240" />
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="auth.can('operator')"
              size="small"
              type="success"
              :loading="rowBusy === `${row.pkg}:launch`"
              @click="appAction('launch', row.pkg, '启动')"
              >启动</el-button
            >
            <el-button
              v-if="auth.can('operator')"
              size="small"
              type="warning"
              :loading="rowBusy === `${row.pkg}:stop`"
              @click="appAction('stop', row.pkg, '强停')"
              >强停</el-button
            >
            <el-button
              v-if="auth.can('operator')"
              size="small"
              :loading="rowBusy === `${row.pkg}:clear`"
              @click="appAction('clear', row.pkg, '清数据', true)"
              >清数据</el-button
            >
            <el-button
              v-if="auth.can('operator')"
              size="small"
              type="danger"
              :loading="rowBusy === `${row.pkg}:uninstall`"
              @click="appAction('uninstall', row.pkg, '卸载', true)"
              >卸载</el-button
            >
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="curDeviceId ? '未获取到已装应用' : '请选择设备'" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <!-- ② 批量应用管理 -->
    <el-card shadow="never">
      <div style="font-weight: 600; margin-bottom: 12px">② 批量应用管理</div>
      <el-row :gutter="14">
        <el-col :span="12">
          <el-table
            :data="store.list"
            border
            stripe
            size="small"
            max-height="360"
            @selection-change="onBatchSelect"
          >
            <el-table-column type="selection" width="46" />
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="name" label="名称" min-width="120" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="statusType[row.status]" size="small">{{
                  statusText[row.status] || row.status
                }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <el-tag type="primary" style="margin-top: 8px">已选 {{ batchIds.length }} 台</el-tag>
        </el-col>

        <el-col :span="12">
          <div style="font-weight: 600; margin-bottom: 8px">按包名批量操作</div>
          <el-input v-model="batchPkg" placeholder="包名，如 com.android.chrome" clearable style="margin-bottom: 10px" />
          <el-button-group style="margin-bottom: 16px">
            <el-button v-if="auth.can('operator')" type="success" @click="batchAppAction('launch', '批量启动', false)">批量启动</el-button>
            <el-button v-if="auth.can('operator')" type="warning" @click="batchAppAction('stop', '批量强停', false)">批量强停</el-button>
            <el-button v-if="auth.can('operator')" type="danger" @click="batchAppAction('uninstall', '批量卸载', true)">批量卸载</el-button>
          </el-button-group>

          <div style="font-weight: 600; margin: 8px 0">批量安装 APK</div>
          <el-input v-model="batchApk" placeholder="APK 下载地址（URL）">
            <template #append><el-button v-if="auth.can('operator')" @click="batchInstall">批量安装</el-button></template>
          </el-input>

          <el-progress
            v-if="store.batchProgress"
            :percentage="progressPct"
            :status="progressPct === 100 ? 'success' : ''"
            style="margin-top: 16px"
          />
          <div
            v-if="store.batchProgress"
            style="font-size: 12px; color: #86868b; margin-top: 4px"
          >
            {{ store.batchProgress.action }}：{{ store.batchProgress.done }} /
            {{ store.batchProgress.total }}
          </div>
          <div v-if="lastResult" style="margin-top: 10px">
            <el-tag type="success">{{ lastResult.label }} 成功 {{ lastResult.ok }}</el-tag>
            <el-tag v-if="lastResult.failed" type="danger" style="margin-left: 8px"
              >失败 {{ lastResult.failed }}</el-tag
            >
            <el-tag type="info" style="margin-left: 8px">共 {{ lastResult.total }}</el-tag>
          </div>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>
