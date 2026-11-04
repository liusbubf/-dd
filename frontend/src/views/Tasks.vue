<script setup>
import { onMounted, onBeforeUnmount, reactive, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/client'
import { useAuth } from '../stores/auth'
import { useDevices } from '../stores/devices'

const store = useDevices()
const auth = useAuth()
const tasks = ref([])
const dlg = ref(false)
const saving = ref(false)
let timer = null

const ACTION_LABELS = {
  open_url: '打开网页',
  tap: '点击',
  swipe: '滑动',
  key: '按键',
  text: '输入文本',
  install: '安装 APK',
}
const actionLabel = (a) => ACTION_LABELS[a] || a

const form = reactive({
  name: '',
  action: 'open_url',
  device_ids: [],
  schedule_type: 'once',
  run_at: null, // Date（once）
  interval_seconds: 60, // interval
  // 各动作参数
  url: 'https://example.com',
  x: 540,
  y: 960,
  x1: 540,
  y1: 1600,
  x2: 540,
  y2: 600,
  duration_ms: 300,
  text: 'hello',
  key: 'home',
  apk_url: 'https://example.com/app.apk',
})

function resetForm() {
  form.name = ''
  form.action = 'open_url'
  form.device_ids = store.list.map((d) => d.id)
  form.schedule_type = 'once'
  form.run_at = new Date(Date.now() + 60 * 1000)
  form.interval_seconds = 60
}

function buildParams() {
  switch (form.action) {
    case 'open_url':
      return { url: form.url }
    case 'tap':
      return { x: Number(form.x), y: Number(form.y) }
    case 'swipe':
      return {
        x1: Number(form.x1),
        y1: Number(form.y1),
        x2: Number(form.x2),
        y2: Number(form.y2),
        duration_ms: Number(form.duration_ms),
      }
    case 'text':
      return { text: form.text }
    case 'key':
      return { key: form.key }
    case 'install':
      return { apk_url: form.apk_url }
    default:
      return {}
  }
}

async function load() {
  try {
    const { data } = await http.get('/tasks')
    tasks.value = data
  } catch (e) {
    /* 静默：自动刷新失败不打扰 */
  }
}

function openCreate() {
  resetForm()
  dlg.value = true
}

async function save() {
  if (!form.name) return ElMessage.warning('请填写任务名称')
  if (!form.device_ids.length) return ElMessage.warning('请选择目标设备')
  if (form.schedule_type === 'once' && !form.run_at) return ElMessage.warning('请选择运行时间')
  if (form.schedule_type === 'interval' && !(form.interval_seconds > 0))
    return ElMessage.warning('请填写正的间隔秒数')

  saving.value = true
  try {
    const body = {
      name: form.name,
      action: form.action,
      params: buildParams(),
      device_ids: form.device_ids,
      schedule_type: form.schedule_type,
      run_at: form.schedule_type === 'once' ? new Date(form.run_at).toISOString() : null,
      interval_seconds: form.schedule_type === 'interval' ? Number(form.interval_seconds) : null,
      enabled: true,
    }
    await http.post('/tasks', body)
    ElMessage.success('任务已创建')
    dlg.value = false
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  } finally {
    saving.value = false
  }
}

async function toggle(row) {
  try {
    await http.patch(`/tasks/${row.id}`, { enabled: row.enabled })
    await load()
  } catch (e) {
    row.enabled = !row.enabled // 回滚 UI
    ElMessage.error(e?.response?.data?.detail || '更新失败')
  }
}

async function runNow(row) {
  try {
    const { data } = await http.post(`/tasks/${row.id}/run-now`)
    const r = data.last_result
    ElMessage.success(`已执行：成功 ${r?.ok ?? 0}/${r?.total ?? 0}`)
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '执行失败')
  }
}

async function del(row) {
  try {
    await ElMessageBox.confirm(`确认删除任务「${row.name}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  await http.delete(`/tasks/${row.id}`)
  ElMessage.success('已删除')
  await load()
}

const fmt = (v) => (v ? new Date(v).toLocaleString() : '—')

const deviceName = (id) => store.byId(id)?.name || `#${id}`

onMounted(async () => {
  await store.refresh()
  await load()
  timer = setInterval(load, 5000)
})
onBeforeUnmount(() => timer && clearInterval(timer))
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span style="font-weight: 600">任务调度 · 定时 / 循环批量指令下发</span>
      <div class="spacer"></div>
      <el-button v-if="auth.can('operator')" type="primary" @click="openCreate">创建任务</el-button>
    </div>

    <el-table :data="tasks" border>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="任务名称" min-width="140" />
      <el-table-column label="动作" width="110">
        <template #default="{ row }">
          <el-tag size="small">{{ actionLabel(row.action) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="目标设备" width="100">
        <template #default="{ row }">{{ row.device_ids.length }} 台</template>
      </el-table-column>
      <el-table-column label="类型" width="130">
        <template #default="{ row }">
          <el-tag :type="row.schedule_type === 'interval' ? 'warning' : 'info'" size="small">
            {{ row.schedule_type === 'interval' ? `循环 · ${row.interval_seconds}s` : '定时（单次）' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-switch v-model="row.enabled" :disabled="!auth.can('operator')" @change="toggle(row)" />
        </template>
      </el-table-column>
      <el-table-column label="下次运行" min-width="170">
        <template #default="{ row }">{{ row.enabled ? fmt(row.next_run) : '—' }}</template>
      </el-table-column>
      <el-table-column label="上次结果" min-width="150">
        <template #default="{ row }">
          <span v-if="!row.last_result" style="color: #86868b">未运行</span>
          <el-tag v-else :type="row.last_result.failed ? 'danger' : 'success'" size="small">
            成功 {{ row.last_result.ok }}/{{ row.last_result.total }}
          </el-tag>
          <span v-if="row.last_run" style="color: #86868b; font-size: 12px; margin-left: 6px">
            {{ fmt(row.last_run) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="190" fixed="right">
        <template #default="{ row }">
          <el-button v-if="auth.can('operator')" size="small" type="primary" @click="runNow(row)">立即执行</el-button>
          <el-button v-if="auth.can('operator')" size="small" type="danger" @click="del(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!tasks.length" description="暂无调度任务，点右上「创建任务」" />

    <el-dialog v-model="dlg" title="创建调度任务" width="620px">
      <el-form label-width="96px">
        <el-form-item label="任务名称">
          <el-input v-model="form.name" placeholder="例如：每分钟刷新首页" />
        </el-form-item>

        <el-form-item label="动作">
          <el-select v-model="form.action" style="width: 100%">
            <el-option v-for="(label, val) in ACTION_LABELS" :key="val" :label="label" :value="val" />
          </el-select>
        </el-form-item>

        <!-- 动作参数（随动作变化） -->
        <el-form-item v-if="form.action === 'open_url'" label="网址 URL">
          <el-input v-model="form.url" placeholder="https://…" />
        </el-form-item>
        <el-form-item v-else-if="form.action === 'tap'" label="坐标">
          <el-input v-model.number="form.x" style="width: 120px" placeholder="x" />
          <span style="margin: 0 8px">,</span>
          <el-input v-model.number="form.y" style="width: 120px" placeholder="y" />
          <span style="color: #86868b; font-size: 12px; margin-left: 8px">按 1080×1920 折算</span>
        </el-form-item>
        <el-form-item v-else-if="form.action === 'swipe'" label="滑动">
          <div style="display: flex; gap: 6px; flex-wrap: wrap; align-items: center">
            <el-input v-model.number="form.x1" style="width: 80px" placeholder="x1" />
            <el-input v-model.number="form.y1" style="width: 80px" placeholder="y1" />
            <span>→</span>
            <el-input v-model.number="form.x2" style="width: 80px" placeholder="x2" />
            <el-input v-model.number="form.y2" style="width: 80px" placeholder="y2" />
            <el-input v-model.number="form.duration_ms" style="width: 100px" placeholder="时长ms" />
          </div>
        </el-form-item>
        <el-form-item v-else-if="form.action === 'text'" label="文本">
          <el-input v-model="form.text" />
        </el-form-item>
        <el-form-item v-else-if="form.action === 'key'" label="按键">
          <el-select v-model="form.key" style="width: 100%">
            <el-option v-for="k in ['back', 'home', 'menu', 'power', 'volume_up', 'volume_down', 'enter']" :key="k" :label="k" :value="k" />
          </el-select>
        </el-form-item>
        <el-form-item v-else-if="form.action === 'install'" label="APK URL">
          <el-input v-model="form.apk_url" placeholder="https://…/app.apk" />
        </el-form-item>

        <el-form-item label="目标设备">
          <el-select v-model="form.device_ids" multiple filterable style="width: 100%" placeholder="选择设备">
            <el-option v-for="d in store.list" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>

        <el-form-item label="调度类型">
          <el-radio-group v-model="form.schedule_type">
            <el-radio-button value="once">定时（单次）</el-radio-button>
            <el-radio-button value="interval">循环</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="form.schedule_type === 'once'" label="运行时间">
          <el-date-picker v-model="form.run_at" type="datetime" placeholder="选择运行时间" style="width: 100%" />
        </el-form-item>
        <el-form-item v-else label="间隔（秒）">
          <el-input-number v-model="form.interval_seconds" :min="5" :step="5" />
          <span style="color: #86868b; font-size: 12px; margin-left: 10px">每隔 N 秒下发一次</span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>
