<script setup>
import { onMounted, ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'
import http from '../api/client'
import { useDevices } from '../stores/devices'

const store = useDevices()
const auth = useAuth()
const scripts = ref([])

// ---------- 回放 ----------
const runDlg = ref(false)
const current = ref(null)
const chosen = ref([])
const lastRun = ref(null)
const running = ref(false)

// ---------- 可视化编辑 ----------
const editDlg = ref(false)
const editing = ref({ id: null, name: '', description: '', steps: [] })

// ---------- 模板库 ----------
const tplDlg = ref(false)
const templates = ref([])

// ---------- 导入 ----------
const importDlg = ref(false)
const importText = ref('')
const fileInput = ref(null)

// 动作元数据：驱动参数输入的字段渲染
const KEY_OPTIONS = ['back', 'home', 'menu', 'recent', 'enter', 'power', 'volume_up', 'volume_down']
const ACTIONS = [
  { value: 'open_url', label: '打开网页', fields: [{ key: 'url', label: 'URL', type: 'text' }] },
  { value: 'tap', label: '点击', fields: [
    { key: 'x', label: 'X', type: 'number' },
    { key: 'y', label: 'Y', type: 'number' },
  ] },
  { value: 'swipe', label: '滑动', fields: [
    { key: 'x1', label: 'X1', type: 'number' },
    { key: 'y1', label: 'Y1', type: 'number' },
    { key: 'x2', label: 'X2', type: 'number' },
    { key: 'y2', label: 'Y2', type: 'number' },
    { key: 'duration_ms', label: '时长ms', type: 'number' },
  ] },
  { value: 'text', label: '输入文本', fields: [{ key: 'text', label: '文本', type: 'text' }] },
  { value: 'key', label: '按键', fields: [{ key: 'key', label: '按键', type: 'select', options: KEY_OPTIONS }] },
  { value: 'wait', label: '等待', fields: [{ key: 'seconds', label: '秒(≤30)', type: 'number' }] },
  { value: 'loop', label: '循环', fields: [{ key: 'count', label: '次数(≤100)', type: 'number' }] },
]
// 循环体内不再允许嵌套循环（后端最多支持 3 层，编辑器 UI 保持 2 层直观）
const SUB_ACTIONS = ACTIONS.filter((a) => a.value !== 'loop')

function fieldsOf(action) {
  const a = ACTIONS.find((x) => x.value === action)
  return a ? a.fields : []
}

function defaultParams(action) {
  switch (action) {
    case 'open_url': return { url: 'https://' }
    case 'tap': return { x: 0, y: 0 }
    case 'swipe': return { x1: 0, y1: 0, x2: 0, y2: 0, duration_ms: 300 }
    case 'text': return { text: '' }
    case 'key': return { key: 'back' }
    case 'wait': return { seconds: 1 }
    case 'loop': return { count: 2, steps: [] }
    default: return {}
  }
}

function onAction(step) {
  step.params = defaultParams(step.action)
}
function addStep(list) {
  list.push({ action: 'tap', params: defaultParams('tap') })
}
function moveStep(list, i, dir) {
  const j = i + dir
  if (j < 0 || j >= list.length) return
  const t = list[i]
  list[i] = list[j]
  list[j] = t
}
function removeStep(list, i) {
  list.splice(i, 1)
}

async function load() {
  const { data } = await api.listScripts()
  scripts.value = data
}
onMounted(async () => {
  await store.refresh()
  await load()
})

// ---------- 新建 / 编辑 ----------
function newScript() {
  editing.value = { id: null, name: '', description: '', steps: [] }
  editDlg.value = true
}
function editScript(s) {
  editing.value = {
    id: s.id,
    name: s.name,
    description: s.description || '',
    steps: JSON.parse(JSON.stringify(s.steps || [])),
  }
  editDlg.value = true
}
const editTitle = computed(() =>
  editing.value.id == null ? '新建脚本' : `编辑脚本 #${editing.value.id}`,
)
async function saveScript() {
  if (!editing.value.name) return ElMessage.warning('请填写脚本名称')
  const body = {
    name: editing.value.name,
    description: editing.value.description,
    steps: editing.value.steps,
  }
  try {
    if (editing.value.id == null) {
      await api.createScript(body)
    } else {
      await http.put(`/scripts/${editing.value.id}`, body)
    }
    ElMessage.success('已保存')
    editDlg.value = false
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
}

// ---------- 模板库 ----------
async function openTemplates() {
  try {
    const { data } = await http.get('/scripts/templates')
    templates.value = data
    tplDlg.value = true
  } catch {
    ElMessage.error('加载模板失败')
  }
}
async function useTemplate(i) {
  try {
    await http.post('/scripts/from-template', { template_index: i })
    ElMessage.success('已从模板创建脚本')
    tplDlg.value = false
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}

// ---------- 导入 / 导出 ----------
function openImport() {
  importText.value = ''
  importDlg.value = true
}
function pickFile() {
  fileInput.value?.click()
}
function onFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    importText.value = String(reader.result || '')
  }
  reader.readAsText(file)
  e.target.value = ''
}
async function doImport() {
  let payload
  try {
    payload = JSON.parse(importText.value)
  } catch {
    return ElMessage.error('JSON 解析失败，请检查内容')
  }
  try {
    await http.post('/scripts/import', {
      name: payload.name || '导入脚本',
      description: payload.description || '',
      steps: payload.steps || [],
    })
    ElMessage.success('导入成功')
    importDlg.value = false
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '导入失败')
  }
}
async function exportScript(s) {
  try {
    const { data } = await http.get(`/scripts/${s.id}/export`)
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${s.name || 'script'}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    ElMessage.error('导出失败')
  }
}

// ---------- 回放 ----------
function openRun(s) {
  current.value = s
  chosen.value = store.list.map((d) => d.id)
  lastRun.value = null
  runDlg.value = true
}
async function doRun() {
  running.value = true
  try {
    const { data } = await api.runScript(current.value.id, chosen.value)
    lastRun.value = data
    ElMessage.success(`回放完成：${data.status === 'success' ? '全部成功' : '部分失败'}`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '回放失败')
  } finally {
    running.value = false
  }
}

async function del(s) {
  await api.deleteScript(s.id)
  await load()
  ElMessage.success('已删除')
}

async function seedDemo() {
  await api.createScript({
    name: '演示脚本：开网页并操作',
    steps: [
      { action: 'open_url', params: { url: 'https://whoer.net' } },
      { action: 'wait', params: { seconds: 0.3 } },
      { action: 'swipe', params: { x1: 540, y1: 1600, x2: 540, y2: 600 } },
      { action: 'tap', params: { x: 300, y: 500 } },
    ],
  })
  await load()
  ElMessage.success('已生成示例脚本')
}

function stepSummary(step) {
  if (step.action === 'loop') {
    const n = (step.params?.steps || []).length
    return `循环 ${step.params?.count ?? 0} 次 · ${n} 子步`
  }
  return step.action
}
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span style="font-weight: 600">脚本引擎 · 可视化编辑 → 跨设备回放</span>
      <div class="spacer"></div>
      <el-button v-if="auth.can('operator')" type="primary" :icon="'Plus'" @click="newScript">新建脚本</el-button>
      <el-button :icon="'Collection'" @click="openTemplates">模板库</el-button>
      <el-button v-if="auth.can('operator')" :icon="'Upload'" @click="openImport">导入</el-button>
      <el-button v-if="auth.can('operator')" @click="seedDemo">生成示例脚本</el-button>
    </div>

    <el-table :data="scripts" border>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="脚本名称" min-width="160" />
      <el-table-column label="步骤数" width="90">
        <template #default="{ row }">{{ row.steps.length }}</template>
      </el-table-column>
      <el-table-column label="步骤预览" min-width="240">
        <template #default="{ row }">
          <el-tag
            v-for="(s, i) in row.steps"
            :key="i"
            :type="s.action === 'loop' ? 'warning' : 'info'"
            size="small"
            style="margin: 2px"
          >{{ stepSummary(s) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="330">
        <template #default="{ row }">
          <el-button v-if="auth.can('operator')" size="small" @click="editScript(row)">编辑</el-button>
          <el-button v-if="auth.can('operator')" size="small" type="primary" @click="openRun(row)">回放</el-button>
          <el-button size="small" @click="exportScript(row)">导出</el-button>
          <el-button v-if="auth.can('operator')" size="small" type="danger" @click="del(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!scripts.length" description="暂无脚本，点右上「新建脚本」/「模板库」，或去单机操控页录制" />

    <!-- ===== 可视化编辑器 ===== -->
    <el-dialog v-model="editDlg" :title="editTitle" width="780px" top="5vh">
      <el-form label-width="64px">
        <el-form-item label="名称">
          <el-input v-model="editing.name" placeholder="脚本名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editing.description" placeholder="可选描述" />
        </el-form-item>
      </el-form>

      <div class="steps-head">
        <span style="font-weight: 600">步骤（{{ editing.steps.length }}）</span>
        <el-button size="small" type="primary" plain :icon="'Plus'" @click="addStep(editing.steps)">添加步骤</el-button>
      </div>

      <div v-for="(step, i) in editing.steps" :key="i" class="step-card">
        <div class="step-row">
          <span class="idx">{{ i + 1 }}</span>
          <el-select v-model="step.action" size="small" style="width: 108px" @change="onAction(step)">
            <el-option v-for="a in ACTIONS" :key="a.value" :label="a.label" :value="a.value" />
          </el-select>
          <template v-for="f in fieldsOf(step.action)" :key="f.key">
            <el-select
              v-if="f.type === 'select'"
              v-model="step.params[f.key]"
              size="small"
              :placeholder="f.label"
              style="width: 116px"
            >
              <el-option v-for="o in f.options" :key="o" :label="o" :value="o" />
            </el-select>
            <el-input
              v-else-if="f.type === 'number'"
              v-model.number="step.params[f.key]"
              size="small"
              type="number"
              :placeholder="f.label"
              style="width: 92px"
            />
            <el-input
              v-else
              v-model="step.params[f.key]"
              size="small"
              :placeholder="f.label"
              style="width: 220px"
            />
          </template>
          <div class="spacer"></div>
          <el-button-group>
            <el-button size="small" :icon="'Top'" :disabled="i === 0" @click="moveStep(editing.steps, i, -1)" />
            <el-button size="small" :icon="'Bottom'" :disabled="i === editing.steps.length - 1" @click="moveStep(editing.steps, i, 1)" />
            <el-button size="small" type="danger" :icon="'Delete'" @click="removeStep(editing.steps, i)" />
          </el-button-group>
        </div>

        <!-- 循环体（逻辑控制）：嵌套子步骤 -->
        <div v-if="step.action === 'loop'" class="loop-body">
          <div class="steps-head sub">
            <span style="color: #b88230">循环体 · 重复 {{ step.params.count }} 次（{{ (step.params.steps || []).length }} 子步）</span>
            <el-button size="small" plain :icon="'Plus'" @click="addStep(step.params.steps)">添加子步骤</el-button>
          </div>
          <div v-for="(sub, j) in step.params.steps" :key="j" class="step-row sub">
            <span class="idx">{{ i + 1 }}.{{ j + 1 }}</span>
            <el-select v-model="sub.action" size="small" style="width: 108px" @change="onAction(sub)">
              <el-option v-for="a in SUB_ACTIONS" :key="a.value" :label="a.label" :value="a.value" />
            </el-select>
            <template v-for="f in fieldsOf(sub.action)" :key="f.key">
              <el-select
                v-if="f.type === 'select'"
                v-model="sub.params[f.key]"
                size="small"
                :placeholder="f.label"
                style="width: 116px"
              >
                <el-option v-for="o in f.options" :key="o" :label="o" :value="o" />
              </el-select>
              <el-input
                v-else-if="f.type === 'number'"
                v-model.number="sub.params[f.key]"
                size="small"
                type="number"
                :placeholder="f.label"
                style="width: 92px"
              />
              <el-input
                v-else
                v-model="sub.params[f.key]"
                size="small"
                :placeholder="f.label"
                style="width: 200px"
              />
            </template>
            <div class="spacer"></div>
            <el-button-group>
              <el-button size="small" :icon="'Top'" :disabled="j === 0" @click="moveStep(step.params.steps, j, -1)" />
              <el-button size="small" :icon="'Bottom'" :disabled="j === step.params.steps.length - 1" @click="moveStep(step.params.steps, j, 1)" />
              <el-button size="small" type="danger" :icon="'Delete'" @click="removeStep(step.params.steps, j)" />
            </el-button-group>
          </div>
          <el-empty v-if="!(step.params.steps || []).length" description="循环体为空，点「添加子步骤」" :image-size="48" />
        </div>
      </div>
      <el-empty v-if="!editing.steps.length" description="还没有步骤，点「添加步骤」开始编排" :image-size="60" />

      <template #footer>
        <el-button @click="editDlg = false">取消</el-button>
        <el-button type="primary" @click="saveScript">保存</el-button>
      </template>
    </el-dialog>

    <!-- ===== 模板库 ===== -->
    <el-dialog v-model="tplDlg" title="模板库" width="620px">
      <el-table :data="templates" border>
        <el-table-column label="模板" min-width="180">
          <template #default="{ row }">
            <div style="font-weight: 600">{{ row.name }}</div>
            <div style="color: #86868b; font-size: 12px">{{ row.description }}</div>
          </template>
        </el-table-column>
        <el-table-column label="步骤" width="80" align="center">
          <template #default="{ row }">{{ row.steps.length }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="center">
          <template #default="{ $index }">
            <el-button size="small" type="primary" @click="useTemplate($index)">使用</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="tplDlg = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- ===== 导入 ===== -->
    <el-dialog v-model="importDlg" title="导入脚本(JSON)" width="560px">
      <div style="margin-bottom: 8px">
        <el-button :icon="'Document'" @click="pickFile">选择 JSON 文件</el-button>
        <input ref="fileInput" type="file" accept=".json,application/json" style="display: none" @change="onFile" />
        <span style="color: #86868b; font-size: 12px; margin-left: 8px">或直接粘贴 {name, description, steps}</span>
      </div>
      <el-input v-model="importText" type="textarea" :rows="10" placeholder='{"name":"…","description":"…","steps":[{"action":"open_url","params":{"url":"https://…"}}]}' />
      <template #footer>
        <el-button @click="importDlg = false">取消</el-button>
        <el-button type="primary" @click="doImport">导入</el-button>
      </template>
    </el-dialog>

    <!-- ===== 回放 ===== -->
    <el-dialog v-model="runDlg" :title="`回放：${current?.name}`" width="560px">
      <div style="margin-bottom: 8px">选择目标设备（{{ chosen.length }} 台）</div>
      <el-select v-model="chosen" multiple filterable style="width: 100%" placeholder="选择设备">
        <el-option v-for="d in store.list" :key="d.id" :label="`${d.name} · ${d.fingerprint?.network?.exit_ip}`" :value="d.id" />
      </el-select>

      <div v-if="lastRun" style="margin-top: 16px">
        <el-alert :type="lastRun.status === 'success' ? 'success' : 'error'" :closable="false"
          :title="`运行 #${lastRun.id} · ${lastRun.status === 'success' ? '全部成功' : '部分失败'}`" />
        <el-table :data="lastRun.results" size="small" border style="margin-top: 10px">
          <el-table-column prop="name" label="设备" />
          <el-table-column label="结果" width="90">
            <template #default="{ row }">
              <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="步骤">
            <template #default="{ row }">
              <el-tag
                v-for="(s, i) in row.steps"
                :key="i"
                :type="s.ok ? 'success' : 'danger'"
                size="small"
                style="margin: 1px"
              >{{ s.loop ? `循环×${s.count}(${s.succeeded}/${s.executed})` : s.action }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <template #footer>
        <el-button @click="runDlg = false">关闭</el-button>
        <el-button type="primary" :loading="running" @click="doRun">开始回放</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.steps-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 10px 0 6px;
}
.steps-head.sub {
  margin: 6px 0;
}
.step-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
  background: var(--el-fill-color-blank);
}
.step-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.step-row.sub {
  padding: 4px 0;
}
.step-row .idx {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 22px;
  padding: 0 6px;
  border-radius: 6px;
  background: var(--el-fill-color);
  color: #86868b;
  font-size: 12px;
}
.loop-body {
  margin-top: 8px;
  padding: 6px 10px 4px;
  border-left: 3px solid #f2c26b;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}
.spacer {
  flex: 1;
}
</style>
