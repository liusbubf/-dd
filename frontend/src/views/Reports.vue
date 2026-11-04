<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../api/client'

// 状态色板：与数据看板保持一致
const STATUS_META = {
  running: { label: '运行中', color: '#34c759', tag: 'success' },
  stopped: { label: '已停止', color: '#8e8e93', tag: 'info' },
  creating: { label: '创建中', color: '#ff9f0a', tag: 'warning' },
  error: { label: '异常', color: '#ff3b30', tag: 'danger' },
}

const summary = ref({
  total_devices: 0,
  total_groups: 0,
  total_scripts: 0,
  total_tasks: 0,
  unique_exit_ips: 0,
  by_status: [],
  by_model: [],
  by_group: [],
  script_runs: { total: 0, success: 0, failed: 0, running: 0 },
})

const loading = ref(false)
const exporting = ref(false)
const errored = ref(false)
const lastUpdated = ref(null)

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/reports/summary')
    summary.value = data
    lastUpdated.value = new Date()
    errored.value = false
  } catch (e) {
    errored.value = true
    ElMessage.error('报表数据获取失败')
  } finally {
    loading.value = false
  }
}

// 携带鉴权头拉取 CSV（axios 会注入 JWT），再以 blob 触发浏览器下载
async function exportCsv() {
  exporting.value = true
  try {
    const { data } = await http.get('/reports/devices.csv', { responseType: 'blob' })
    const url = window.URL.createObjectURL(new Blob([data], { type: 'text/csv;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `devices-${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
    ElMessage.success('已导出设备明细 CSV')
  } catch (e) {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

// KPI 磁贴
const kpis = computed(() => {
  const s = summary.value
  return [
    { key: 'devices', label: '设备总数', value: s.total_devices, color: '#007aff', icon: 'Iphone' },
    { key: 'groups', label: '分组数', value: s.total_groups, color: '#5856d6', icon: 'FolderOpened' },
    { key: 'scripts', label: '脚本数', value: s.total_scripts, color: '#0a84ff', icon: 'VideoPlay' },
    { key: 'tasks', label: '任务数', value: s.total_tasks, color: '#ff9f0a', icon: 'Timer' },
    { key: 'ips', label: '独立出口 IP', value: s.unique_exit_ips, color: '#34c759', icon: 'Connection' },
    { key: 'runs', label: '脚本运行次数', value: s.script_runs.total, color: '#af52de', icon: 'DataLine' },
  ]
})

const maxModel = computed(() => Math.max(1, ...summary.value.by_model.map((m) => m.count)))
const maxGroup = computed(() => Math.max(1, ...summary.value.by_group.map((g) => g.count)))

function statusMeta(k) {
  return STATUS_META[k] || { label: k, color: '#8e8e93', tag: 'info' }
}
function fmtTime(d) {
  return d ? d.toLocaleTimeString('zh-CN', { hour12: false }) : '—'
}

onMounted(load)
</script>

<template>
  <div class="page reports">
    <div class="toolbar">
      <span style="font-weight: 600; font-size: 16px">统计报表</span>
      <el-tag v-if="errored" type="danger" size="small" effect="plain">数据获取失败</el-tag>
      <div class="spacer" style="flex: 1"></div>
      <span class="muted">更新时间：{{ fmtTime(lastUpdated) }}</span>
      <el-button :icon="'Refresh'" size="small" :loading="loading" @click="load">刷新</el-button>
      <el-button type="primary" :icon="'Download'" size="small" :loading="exporting" @click="exportCsv">
        导出 CSV
      </el-button>
    </div>

    <!-- KPI 磁贴 -->
    <el-row :gutter="14">
      <el-col v-for="k in kpis" :key="k.key" :xs="12" :sm="8" :md="4">
        <el-card shadow="hover" class="kpi-card" body-style="padding: 16px">
          <div class="kpi-icon" :style="{ background: k.color + '1a', color: k.color }">
            <el-icon :size="20"><component :is="k.icon" /></el-icon>
          </div>
          <div class="kpi-meta">
            <div class="kpi-value">{{ k.value }}</div>
            <div class="kpi-label">{{ k.label }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 状态分布 + 脚本运行成败 -->
    <el-row :gutter="14" class="block">
      <el-col :xs="24" :md="12">
        <el-card shadow="never" body-style="padding: 18px 20px" class="fill">
          <div class="block-head"><span class="block-title">设备状态分布</span></div>
          <el-table :data="summary.by_status" size="small" style="width: 100%">
            <el-table-column label="状态" min-width="120">
              <template #default="{ row }">
                <el-tag :type="statusMeta(row.status).tag" size="small" effect="light">
                  {{ row.label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="count" label="数量" width="100" align="right" />
            <el-table-column label="占比" min-width="120">
              <template #default="{ row }">
                {{ summary.total_devices ? ((row.count / summary.total_devices) * 100).toFixed(1) : '0.0' }}%
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="12">
        <el-card shadow="never" body-style="padding: 18px 20px" class="fill">
          <div class="block-head"><span class="block-title">脚本运行统计</span></div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="运行总次数">{{ summary.script_runs.total }}</el-descriptions-item>
            <el-descriptions-item label="进行中">{{ summary.script_runs.running }}</el-descriptions-item>
            <el-descriptions-item label="成功">
              <span style="color: #34c759; font-weight: 600">{{ summary.script_runs.success }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="失败">
              <span style="color: #ff3b30; font-weight: 600">{{ summary.script_runs.failed }}</span>
            </el-descriptions-item>
          </el-descriptions>
          <div class="muted" style="margin-top: 12px">
            成功率：{{
              summary.script_runs.total
                ? ((summary.script_runs.success / summary.script_runs.total) * 100).toFixed(1)
                : '0.0'
            }}%
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 机型分布 + 分组分布 -->
    <el-row :gutter="14" class="block">
      <el-col :xs="24" :md="12">
        <el-card shadow="never" body-style="padding: 18px 20px" class="fill">
          <div class="block-head">
            <span class="block-title">机型分布</span>
            <span class="muted">{{ summary.by_model.length }} 种机型</span>
          </div>
          <div v-if="summary.by_model.length" class="hbar-list">
            <div v-for="m in summary.by_model" :key="m.model" class="hbar-row">
              <span class="hbar-label" :title="m.model">{{ m.model }}</span>
              <div class="hbar-track">
                <div class="hbar-fill model" :style="{ width: (m.count / maxModel) * 100 + '%' }"></div>
              </div>
              <span class="hbar-count">{{ m.count }}</span>
            </div>
          </div>
          <el-empty v-else :image-size="60" description="暂无数据" />
        </el-card>
      </el-col>

      <el-col :xs="24" :md="12">
        <el-card shadow="never" body-style="padding: 18px 20px" class="fill">
          <div class="block-head">
            <span class="block-title">分组分布</span>
            <span class="muted">{{ summary.total_groups }} 个分组</span>
          </div>
          <div v-if="summary.by_group.length" class="hbar-list">
            <div v-for="g in summary.by_group" :key="g.group_id ?? 'none'" class="hbar-row">
              <span class="hbar-label" :title="g.name">{{ g.name }}</span>
              <div class="hbar-track">
                <div class="hbar-fill group" :style="{ width: (g.count / maxGroup) * 100 + '%' }"></div>
              </div>
              <span class="hbar-count">{{ g.count }}</span>
            </div>
          </div>
          <el-empty v-else :image-size="60" description="暂无分组" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.reports {
  padding: 16px;
}
.reports .toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.reports .muted {
  color: #86868b;
  font-size: 12px;
}

/* KPI 磁贴 */
.kpi-card {
  margin-bottom: 14px;
  border-radius: 12px;
}
.kpi-card :deep(.el-card__body) {
  display: flex;
  align-items: center;
  gap: 12px;
}
.kpi-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.kpi-value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.1;
  color: #1d1d1f;
}
.kpi-label {
  font-size: 12px;
  color: #86868b;
  margin-top: 2px;
}

/* 区块 */
.block {
  margin-bottom: 14px;
}
.block-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 14px;
}
.block-title {
  font-weight: 600;
  font-size: 15px;
  color: #1d1d1f;
}
.fill {
  height: 100%;
  border-radius: 12px;
}

/* 横向条形列表 */
.hbar-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.hbar-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.hbar-label {
  width: 120px;
  flex-shrink: 0;
  font-size: 13px;
  color: #1d1d1f;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hbar-track {
  flex: 1;
  height: 14px;
  background: #f0f1f3;
  border-radius: 7px;
  overflow: hidden;
}
.hbar-fill {
  height: 100%;
  border-radius: 7px;
  min-width: 2px;
  transition: width 0.4s ease;
}
.hbar-fill.model {
  background: linear-gradient(90deg, #0a84ff, #5ac8fa);
}
.hbar-fill.group {
  background: linear-gradient(90deg, #5856d6, #af52de);
}
.hbar-count {
  width: 40px;
  flex-shrink: 0;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
  color: #1d1d1f;
}
</style>
