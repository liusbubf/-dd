<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../api/client'

const items = ref([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(30)

// 筛选条件
const filterUsername = ref('')
const filterAction = ref('')
const filterQ = ref('')
const filterStart = ref('')
const filterEnd = ref('')

// 下拉选项
const actionOptions = ref([])
const userOptions = ref([])

let timer = null

const actionTagMap = {
  '创建用户': 'success',
  '修改用户': 'warning',
  '删除用户': 'danger',
  '创建脚本': 'success',
  '删除脚本': 'danger',
  '执行脚本': 'primary',
}

function actionType(action) {
  return actionTagMap[action] || 'info'
}

async function load(showLoading = false) {
  if (showLoading) loading.value = true
  try {
    const params = { page: page.value, size: pageSize.value }
    if (filterUsername.value) params.username = filterUsername.value
    if (filterAction.value) params.action = filterAction.value
    if (filterQ.value) params.q = filterQ.value
    if (filterStart.value) params.start_date = new Date(filterStart.value).toISOString()
    if (filterEnd.value) params.end_date = new Date(filterEnd.value + 'T23:59:59').toISOString()

    const { data } = await http.get('/audit', { params })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    if (showLoading) ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  try {
    const [aRes, uRes] = await Promise.all([
      http.get('/audit/actions'),
      http.get('/audit/users'),
    ])
    actionOptions.value = aRes.data?.actions || []
    userOptions.value = uRes.data?.users || []
  } catch { /* 选项接口失败不影响主列表 */ }
}

function onPageChange(p) {
  page.value = p
  load(true)
}

function onSizeChange(s) {
  pageSize.value = s
  page.value = 1
  load(true)
}

function onSearch() {
  page.value = 1
  load(true)
}

function onReset() {
  filterUsername.value = ''
  filterAction.value = ''
  filterQ.value = ''
  filterStart.value = ''
  filterEnd.value = ''
  page.value = 1
  load(true)
}

function exportCsv() {
  const params = []
  if (filterStart.value) params.push('start_date=' + new Date(filterStart.value).toISOString())
  if (filterEnd.value) params.push('end_date=' + new Date(filterEnd.value + 'T23:59:59').toISOString())
  const qs = params.length ? '?' + params.join('&') : ''
  window.open('/api/audit/export.csv' + qs)
}

function fmt(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString('zh-CN')
}

function detailText(d) {
  if (d === null || d === undefined || d === '') return '—'
  if (typeof d === 'string') return d
  try { return JSON.stringify(d) } catch { return String(d) }
}

onMounted(() => {
  loadOptions()
  load(true)
  timer = setInterval(() => load(false), 30000)  // 30 秒自动刷新
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span style="font-weight: 600">操作审计日志</span>
      <el-tag type="info" size="small" effect="plain" style="margin-left: 8px">每 30 秒自动刷新</el-tag>
      <div class="spacer"></div>
      <el-button @click="exportCsv" :disabled="total === 0">导出 CSV</el-button>
      <el-button type="primary" @click="load(true)">刷新</el-button>
    </div>

    <!-- 筛选栏 -->
    <div class="filters">
      <el-input v-model="filterQ" placeholder="关键词搜索" clearable style="width: 180px" @clear="onSearch" @keyup.enter="onSearch" />
      <el-select v-model="filterAction" placeholder="操作类型" clearable style="width: 140px" @change="onSearch">
        <el-option v-for="a in actionOptions" :key="a.action" :label="`${a.action} (${a.count})`" :value="a.action" />
      </el-select>
      <el-select v-model="filterUsername" placeholder="操作人" clearable style="width: 140px" @change="onSearch">
        <el-option v-for="u in userOptions" :key="u.username" :label="`${u.username} (${u.count})`" :value="u.username" />
      </el-select>
      <el-date-picker v-model="filterStart" type="date" placeholder="开始日期" style="width: 150px" value-format="YYYY-MM-DD" @change="onSearch" />
      <el-date-picker v-model="filterEnd" type="date" placeholder="结束日期" style="width: 150px" value-format="YYYY-MM-DD" @change="onSearch" />
      <el-button @click="onReset" text>重置</el-button>
    </div>

    <el-table :data="items" v-loading="loading" border stripe style="width: 100%" size="small">
      <el-table-column label="ID" width="70" prop="id" />
      <el-table-column label="时间" width="190">
        <template #default="{ row }">{{ fmt(row.ts) }}</template>
      </el-table-column>
      <el-table-column prop="username" label="操作者" width="130" />
      <el-table-column label="动作" width="140">
        <template #default="{ row }">
          <el-tag :type="actionType(row.action)" size="small">{{ row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="target" label="对象" min-width="150" />
      <el-table-column label="详情" min-width="240">
        <template #default="{ row }">
          <span style="color: var(--color-text-muted); font-size: 12px">{{ detailText(row.detail) }}</span>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination" v-if="total > 0">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 30, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>

    <el-empty v-if="!loading && items.length === 0" description="暂无审计日志" />
  </div>
</template>

<style scoped>
.page {
  padding: 16px;
}
.toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
  gap: 8px;
}
.filters {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.spacer {
  flex: 1;
}
.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
