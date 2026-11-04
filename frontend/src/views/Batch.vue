<script setup>
import { onMounted, onBeforeUnmount, ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'
import { useDevices } from '../stores/devices'
import PhoneFrame from '../components/PhoneFrame.vue'

const store = useDevices()
const auth = useAuth()
const selected = ref(new Set())
const url = ref('https://example.com')
const apk = ref('https://example.com/app.apk')
const textVal = ref('hello')

const selectedIds = computed(() => [...selected.value])
const allSelected = computed(() => store.list.length > 0 && selected.value.size === store.list.length)

function toggle(d) {
  selected.value.has(d.id) ? selected.value.delete(d.id) : selected.value.add(d.id)
  selected.value = new Set(selected.value)
}
function toggleAll() {
  if (allSelected.value) selected.value = new Set()
  else selected.value = new Set(store.list.map((d) => d.id))
}

async function run(action, body, label) {
  if (!selected.value.size) return ElMessage.warning('请先勾选设备')
  store.batchProgress = { action, done: 0, total: selectedIds.value.length }
  try {
    const { data } = await api.batch(action, { device_ids: selectedIds.value, ...body })
    // 不依赖 WS：直接按响应把进度置满，并让预览立即走一次轮询刷新（画面反映新页面）
    store.batchProgress = { action, done: data.total, total: data.total }
    store.lastWsFrameAt = 0
    await store.refresh()
    ElMessage.success(`${label}：成功 ${data.ok}/${data.total}`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '批量操作失败')
  }
}

const progressPct = computed(() => {
  const p = store.batchProgress
  return p && p.total ? Math.round((p.done / p.total) * 100) : 0
})

function subscribe() {
  store.subscribePreviews(store.list.map((d) => d.id), 1)
}
onMounted(async () => {
  await store.refresh()
  subscribe()
})
onBeforeUnmount(() => store.subscribePreviews([], 1))
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-button @click="toggleAll">{{ allSelected ? '取消全选' : '全选' }}</el-button>
      <el-tag type="primary">已选 {{ selected.size }} / {{ store.list.length }}</el-tag>
      <div class="spacer"></div>
    </div>

    <el-card shadow="never" style="margin-bottom: 14px">
      <el-row :gutter="12">
        <el-col :span="10">
          <div style="font-weight: 600; margin-bottom: 8px">① 一键批量开网页（同步）</div>
          <el-input v-model="url" placeholder="https://…">
            <template #append>
              <el-button type="primary" :disabled="!auth.can('operator')" @click="run('open_url', { url }, '批量开网页')">下发</el-button>
            </template>
          </el-input>
        </el-col>
        <el-col :span="8">
          <div style="font-weight: 600; margin-bottom: 8px">② 同步操控（1 控 N）</div>
          <el-button-group>
            <el-button :disabled="!auth.can('operator')" @click="run('tap', { x: 540, y: 960 }, '同步点击')">同步点击中心</el-button>
            <el-button :disabled="!auth.can('operator')" @click="run('swipe', { x1: 540, y1: 1600, x2: 540, y2: 600 }, '同步上滑')">同步上滑</el-button>
            <el-button :disabled="!auth.can('operator')" @click="run('key', { key: 'home' }, '同步 Home')">同步 Home</el-button>
          </el-button-group>
        </el-col>
        <el-col :span="6">
          <div style="font-weight: 600; margin-bottom: 8px">③ 批量输入 / 装 APK</div>
          <el-input v-model="textVal" size="small" style="margin-bottom: 6px">
            <template #append><el-button :disabled="!auth.can('operator')" @click="run('text', { text: textVal }, '批量输入')">输入</el-button></template>
          </el-input>
          <el-input v-model="apk" size="small" placeholder="APK URL">
            <template #append><el-button :disabled="!auth.can('operator')" @click="run('install', { apk_url: apk }, '批量装 APK')">安装</el-button></template>
          </el-input>
        </el-col>
      </el-row>
      <el-progress
        v-if="store.batchProgress"
        :percentage="progressPct"
        :status="progressPct === 100 ? 'success' : ''"
        style="margin-top: 14px"
      />
      <div v-if="store.batchProgress" style="font-size: 12px; color: #86868b; margin-top: 4px">
        {{ store.batchProgress.action }}：{{ store.batchProgress.done }} / {{ store.batchProgress.total }}
      </div>
    </el-card>

    <div class="grid" style="grid-template-columns: repeat(6, 1fr)">
      <PhoneFrame
        v-for="d in store.list"
        :key="d.id"
        :device="d"
        :frame="store.frames[d.id]"
        selectable
        :selected="selected.has(d.id)"
        @toggle="toggle"
        @open="toggle(d)"
      />
    </div>
    <el-empty v-if="!store.list.length" description="暂无设备" />
  </div>
</template>
