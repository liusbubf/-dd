<script setup>
import { onMounted, onBeforeUnmount, ref, computed } from 'vue'
import http from '../api/client'

// 告警数据（实时计算，不落库）
const data = ref({ generated_at: null, total: 0, by_level: { critical: 0, warning: 0, info: 0 }, alerts: [] })
const rules = ref([])
const loading = ref(false)
const activeRules = ref([]) // 折叠面板：默认收起

let timer = null

// 级别元信息：文案 + 颜色（对齐设备状态色板）
const LEVEL = {
  critical: { label: '严重', type: 'danger', color: '#ff3b30' },
  warning: { label: '警告', type: 'warning', color: '#ff9f0a' },
  info: { label: '提示', type: 'info', color: '#8e8e93' },
}

const alerts = computed(() => data.value.alerts || [])
const byLevel = computed(() => data.value.by_level || { critical: 0, warning: 0, info: 0 })

function fmtTime(ts) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return ts
  }
}

async function load() {
  loading.value = true
  try {
    const { data: d } = await http.get('/alerts/current')
    data.value = d
  } finally {
    loading.value = false
  }
}

async function loadRules() {
  const { data: d } = await http.get('/alerts/rules')
  rules.value = d.rules || []
}

onMounted(() => {
  load()
  loadRules()
  timer = setInterval(load, 5000) // 5s 自动刷新
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span style="font-weight: 600">告警监控</span>
      <el-tag :color="LEVEL.critical.color" effect="dark" style="border: none">
        严重 {{ byLevel.critical || 0 }}
      </el-tag>
      <el-tag :color="LEVEL.warning.color" effect="dark" style="border: none">
        警告 {{ byLevel.warning || 0 }}
      </el-tag>
      <el-tag :color="LEVEL.info.color" effect="dark" style="border: none">
        提示 {{ byLevel.info || 0 }}
      </el-tag>
      <div class="spacer"></div>
      <span style="color: #8e8e93; font-size: 12px">
        更新于 {{ fmtTime(data.generated_at) }} · 每 5 秒自动刷新
      </span>
      <el-button :icon="'Refresh'" :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-table v-if="alerts.length" :data="alerts" border stripe style="width: 100%" size="small">
      <el-table-column label="级别" width="90">
        <template #default="{ row }">
          <el-tag :type="LEVEL[row.level]?.type || 'info'" size="small">
            {{ LEVEL[row.level]?.label || row.level }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="设备" width="160">
        <template #default="{ row }">
          <span>{{ row.device_name }}</span>
          <span style="color: #8e8e93"> #{{ row.device_id }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="message" label="告警信息" min-width="260" />
      <el-table-column label="时间" width="180">
        <template #default="{ row }">{{ fmtTime(row.ts) }}</template>
      </el-table-column>
    </el-table>

    <el-empty v-else description="当前无告警" />

    <el-collapse v-model="activeRules" style="margin-top: 18px">
      <el-collapse-item name="rules">
        <template #title>
          <span style="font-weight: 600">告警规则（{{ rules.length }}）</span>
        </template>
        <el-table :data="rules" border style="width: 100%" size="small">
          <el-table-column prop="name" label="规则" width="140" />
          <el-table-column label="级别" width="90">
            <template #default="{ row }">
              <el-tag :type="LEVEL[row.level]?.type || 'info'" size="small">
                {{ LEVEL[row.level]?.label || row.level }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="说明" min-width="300" />
        </el-table>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>
