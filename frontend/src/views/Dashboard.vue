<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import http from '../api/client'

// 状态色板：与 App 全局状态色保持一致（styles.css 的 .dot.*）
const STATUS_META = {
  running: { label: '运行中', color: '#34c759' },
  stopped: { label: '已停止', color: '#8e8e93' },
  creating: { label: '创建中', color: '#ff9f0a' },
  error: { label: '异常', color: '#ff3b30' },
}

const overview = ref({
  total_devices: 0,
  running: 0,
  stopped: 0,
  error: 0,
  creating: 0,
  total_groups: 0,
  ws_clients: 0,
  unique_exit_ips: 0,
  by_group: [],
  model_distribution: [],
  recent_devices: [],
})

const loading = ref(false)
const errored = ref(false)
const lastUpdated = ref(null)
let timer = null

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/metrics/overview')
    overview.value = data
    lastUpdated.value = new Date()
    errored.value = false
  } catch (e) {
    // 保留上一次数据，标记异常；5s 后自动重试
    errored.value = true
  } finally {
    loading.value = false
  }
}

// KPI 磁贴
const kpis = computed(() => {
  const o = overview.value
  return [
    { key: 'total', label: '总设备', value: o.total_devices, color: '#007aff', icon: 'Iphone' },
    { key: 'running', label: '运行中', value: o.running, color: STATUS_META.running.color, icon: 'VideoPlay' },
    { key: 'stopped', label: '已停止', value: o.stopped, color: STATUS_META.stopped.color, icon: 'VideoPause' },
    { key: 'error', label: '异常', value: o.error, color: STATUS_META.error.color, icon: 'WarningFilled' },
    { key: 'groups', label: '分组数', value: o.total_groups, color: '#5856d6', icon: 'FolderOpened' },
    { key: 'ws', label: '在线 WS 客户端', value: o.ws_clients, color: '#ff9f0a', icon: 'Connection' },
  ]
})

// 状态分段条（stacked bar）
const statusSegments = computed(() => {
  const o = overview.value
  const total = o.total_devices || 0
  return ['running', 'stopped', 'creating', 'error']
    .map((k) => ({
      key: k,
      label: STATUS_META[k].label,
      color: STATUS_META[k].color,
      count: o[k] || 0,
      pct: total ? ((o[k] || 0) / total) * 100 : 0,
    }))
})

const maxModel = computed(() =>
  Math.max(1, ...overview.value.model_distribution.map((m) => m.count)),
)
const maxGroup = computed(() =>
  Math.max(1, ...overview.value.by_group.map((g) => g.count)),
)

const statusText = { running: '运行中', stopped: '已停止', creating: '创建中', error: '异常' }
const statusTagType = { running: 'success', stopped: 'info', creating: 'warning', error: 'danger' }

function fmtTime(d) {
  return d ? d.toLocaleTimeString('zh-CN', { hour12: false }) : '—'
}
function fmtDateTime(s) {
  if (!s) return '—'
  return new Date(s).toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => {
  load()
  timer = setInterval(load, 5000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="page dashboard">
    <div class="toolbar">
      <span style="font-weight: 600; font-size: 16px">数据看板</span>
      <el-tag v-if="errored" type="danger" size="small" effect="plain">数据获取失败，正在重试…</el-tag>
      <el-tag v-else type="info" size="small" effect="plain">每 5 秒自动刷新</el-tag>
      <div class="spacer"></div>
      <span class="muted">更新时间：{{ fmtTime(lastUpdated) }}</span>
      <el-button :icon="'Refresh'" size="small" :loading="loading" @click="load">刷新</el-button>
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

    <!-- 设备状态分布（分段条） -->
    <el-card shadow="never" class="block" body-style="padding: 18px 20px">
      <div class="block-head">
        <span class="block-title">设备状态分布</span>
        <span class="muted">共 {{ overview.total_devices }} 台 · 独立出口 IP {{ overview.unique_exit_ips }} 个</span>
      </div>
      <div
        class="stack-bar"
        role="img"
        :aria-label="statusSegments.map((s) => `${s.label} ${s.count} 台`).join('，')"
      >
        <div
          v-for="s in statusSegments"
          v-show="s.pct > 0"
          :key="s.key"
          class="stack-seg"
          :style="{ width: s.pct + '%', background: s.color }"
          :title="`${s.label} ${s.count} 台（${s.pct.toFixed(1)}%）`"
        ></div>
        <div v-if="!overview.total_devices" class="stack-empty">暂无设备</div>
      </div>
      <div class="legend">
        <div v-for="s in statusSegments" :key="s.key" class="legend-item">
          <span class="legend-dot" :style="{ background: s.color }"></span>
          <span class="legend-label">{{ s.label }}</span>
          <span class="legend-count">{{ s.count }}</span>
        </div>
      </div>
    </el-card>

    <!-- 机型分布 + 分组分布 -->
    <el-row :gutter="14" class="block">
      <el-col :xs="24" :md="12">
        <el-card shadow="never" body-style="padding: 18px 20px" class="fill">
          <div class="block-head">
            <span class="block-title">机型分布</span>
            <span class="muted">{{ overview.model_distribution.length }} 种机型</span>
          </div>
          <div v-if="overview.model_distribution.length" class="hbar-list">
            <div v-for="m in overview.model_distribution" :key="m.model" class="hbar-row">
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
            <span class="muted">{{ overview.total_groups }} 个分组</span>
          </div>
          <div v-if="overview.by_group.length" class="hbar-list">
            <div v-for="g in overview.by_group" :key="g.group_id ?? 'none'" class="hbar-row">
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

    <!-- 最近创建的设备 -->
    <el-card shadow="never" class="block" body-style="padding: 18px 20px">
      <div class="block-head">
        <span class="block-title">最近创建的设备</span>
      </div>
      <el-table :data="overview.recent_devices" size="small" style="width: 100%">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType[row.status]" size="small">{{ statusText[row.status] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="180">
          <template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template>
        </el-table-column>
        <template #empty>暂无设备</template>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.dashboard .muted {
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
  margin-top: 4px;
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
.el-card.block,
.el-card.fill {
  border-radius: 12px;
}

/* 状态分段条 */
.stack-bar {
  display: flex;
  height: 22px;
  width: 100%;
  border-radius: 6px;
  overflow: hidden;
  background: #ebedf0;
}
.stack-seg {
  height: 100%;
  transition: width 0.4s ease;
}
.stack-empty {
  width: 100%;
  text-align: center;
  font-size: 12px;
  color: #86868b;
  line-height: 22px;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  margin-top: 14px;
}
.legend-item {
  display: flex;
  align-items: center;
  font-size: 13px;
}
.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  margin-right: 6px;
}
.legend-label {
  color: #1d1d1f;
  margin-right: 6px;
}
.legend-count {
  font-weight: 600;
  color: #1d1d1f;
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
