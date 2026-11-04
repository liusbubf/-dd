<script setup>
import { onMounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http, { api } from '../api/client'
import { useAuth } from '../stores/auth'

const auth = useAuth()

// 分组树（多级 ≤3 级）
const tree = ref([])
const ungrouped = ref(0)
const maxDepth = ref(3)
const treeLoading = ref(false)

// 设备
const devices = ref([])
const devLoading = ref(false)
const selectedRows = ref([])
const targetGroupId = ref(null)

// 当前选中的分组（点击树节点）
const selectedGroup = ref(null) // { id, name } | null
const deviceFilter = ref('all') // all | selected | ungrouped

const treeProps = { children: 'children', label: 'name' }

const statusType = { running: 'success', stopped: 'info', creating: 'warning', error: 'danger' }
const statusText = { running: '运行中', stopped: '已停止', creating: '创建中', error: '异常' }

// ---------- 数据加载 ----------
async function loadTree() {
  treeLoading.value = true
  try {
    const { data } = await http.get('/groups/tree')
    tree.value = data.roots || []
    ungrouped.value = data.ungrouped_count || 0
    maxDepth.value = data.max_depth || 3
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载分组树失败')
  } finally {
    treeLoading.value = false
  }
}

async function loadDevices() {
  devLoading.value = true
  try {
    const { data } = await api.listDevices()
    devices.value = data
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载设备失败')
  } finally {
    devLoading.value = false
  }
}

async function reloadAll() {
  await Promise.all([loadTree(), loadDevices()])
}

onMounted(reloadAll)

// ---------- 扁平化：用于「目标分组」下拉，带层级缩进 ----------
function flatten(nodes, depth = 0, acc = []) {
  for (const n of nodes) {
    acc.push({ id: n.id, label: '　'.repeat(depth) + n.name, count: n.device_count })
    if (n.children && n.children.length) flatten(n.children, depth + 1, acc)
  }
  return acc
}
const groupOptions = computed(() => flatten(tree.value))
const nameById = computed(() => {
  const m = {}
  const walk = (nodes) => nodes.forEach((n) => {
    m[n.id] = n.name
    if (n.children) walk(n.children)
  })
  walk(tree.value)
  return m
})
function groupName(id) {
  return id == null ? '未分组' : nameById.value[id] || `#${id}`
}

// ---------- 设备过滤 ----------
const filteredDevices = computed(() => {
  if (deviceFilter.value === 'ungrouped') return devices.value.filter((d) => d.group_id == null)
  if (deviceFilter.value === 'selected' && selectedGroup.value)
    return devices.value.filter((d) => d.group_id === selectedGroup.value.id)
  return devices.value
})

function onNodeClick(data) {
  selectedGroup.value = { id: data.id, name: data.name }
  deviceFilter.value = 'selected'
}

// ---------- 分组增删改 ----------
async function createGroup(parentId, parentName) {
  try {
    const { value } = await ElMessageBox.prompt(
      parentId ? `在「${parentName}」下新建子分组` : '新建顶级分组',
      parentId ? '新建子分组' : '新建顶级分组',
      { inputValidator: (v) => (v && v.trim() ? true : '请输入分组名称'), confirmButtonText: '确定', cancelButtonText: '取消' },
    )
    await http.post('/groups', { name: value.trim(), parent_id: parentId ?? null })
    ElMessage.success('分组已创建')
    await loadTree()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}

async function renameNode(data) {
  try {
    const { value } = await ElMessageBox.prompt('新名称', '重命名分组', {
      inputValue: data.name,
      inputValidator: (v) => (v && v.trim() ? true : '请输入分组名称'),
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
    await http.patch(`/groups/${data.id}`, { name: value.trim() })
    ElMessage.success('已重命名')
    await loadTree()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(e?.response?.data?.detail || '重命名失败')
  }
}

async function removeNode(data) {
  try {
    await ElMessageBox.confirm(
      `删除分组「${data.name}」？其下设备将变为未分组，子分组将上提为顶级。`,
      '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await api.deleteGroup(data.id)
    ElMessage.success('已删除')
    if (selectedGroup.value?.id === data.id) {
      selectedGroup.value = null
      deviceFilter.value = 'all'
    }
    await reloadAll()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

// ---------- 拖拽移动分组（re-parent，后端校验层级/环） ----------
function allowDrop(draggingNode, dropNode, type) {
  // 不允许把节点拖成自身子级；其余交给后端 PATCH 校验
  return !(type === 'inner' && draggingNode.data.id === dropNode.data.id)
}

async function onNodeDrop(draggingNode, dropNode, dropType) {
  const id = draggingNode.data.id
  let parentId = null
  if (dropType === 'inner') parentId = dropNode.data.id
  else parentId = dropNode.data.parent_id ?? null
  try {
    await http.patch(`/groups/${id}`, { parent_id: parentId })
    ElMessage.success('分组已移动')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '移动失败')
  } finally {
    await loadTree() // 以服务端为准，重建树（失败时回滚视图）
  }
}

// ---------- 设备移动 ----------
function onSelectionChange(rows) {
  selectedRows.value = rows
}

async function moveDevices(gid) {
  const ids = selectedRows.value.map((r) => r.id)
  if (!ids.length) {
    ElMessage.warning('请先勾选设备')
    return
  }
  try {
    const { data } = await http.post(`/groups/${gid ?? 0}/move-devices`, { device_ids: ids })
    ElMessage.success(`已移动 ${data.moved} 台设备`)
    selectedRows.value = []
    await reloadAll()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '移动失败')
  }
}
</script>

<template>
  <div class="page">
    <el-row :gutter="16">
      <!-- 分组树 -->
      <el-col :span="9">
        <el-card shadow="never" class="card">
          <template #header>
            <div class="card-hd">
              <span>分组树（最多 {{ maxDepth }} 级）</span>
              <div class="spacer"></div>
              <el-button v-if="auth.can('operator')" size="small" type="primary" @click="createGroup(null)">新建顶级分组</el-button>
              <el-button size="small" @click="loadTree">刷新</el-button>
            </div>
          </template>

          <div class="hint">
            <el-tag size="small" type="info" effect="plain">未分组设备 {{ ungrouped }}</el-tag>
            <span class="tip">支持拖拽调整层级</span>
          </div>

          <el-tree
            v-loading="treeLoading"
            :data="tree"
            :props="treeProps"
            node-key="id"
            default-expand-all
            highlight-current
            :draggable="auth.can('operator')"
            :allow-drop="allowDrop"
            @node-click="onNodeClick"
            @node-drop="onNodeDrop"
          >
            <template #default="{ node, data }">
              <span class="tree-node">
                <span class="tree-name">
                  {{ data.name }}
                  <el-tag size="small" type="info" effect="plain" class="cnt">{{ data.device_count }}</el-tag>
                  <span v-if="data.total_count > data.device_count" class="total">共 {{ data.total_count }}</span>
                </span>
                <span class="tree-ops">
                  <el-button
                    v-if="node.level < maxDepth && auth.can('operator')"
                    link
                    type="primary"
                    size="small"
                    @click.stop="createGroup(data.id, data.name)"
                    >新建子分组</el-button
                  >
                  <el-button v-if="auth.can('operator')" link size="small" @click.stop="renameNode(data)">重命名</el-button>
                  <el-button v-if="auth.can('operator')" link type="danger" size="small" @click.stop="removeNode(data)">删除</el-button>
                </span>
              </span>
            </template>
          </el-tree>

          <el-empty v-if="!treeLoading && !tree.length" description="暂无分组，点击「新建顶级分组」开始" :image-size="80" />
        </el-card>
      </el-col>

      <!-- 设备移动面板 -->
      <el-col :span="15">
        <el-card shadow="never" class="card">
          <template #header>
            <div class="card-hd">
              <span>设备移动</span>
              <div class="spacer"></div>
              <el-radio-group v-model="deviceFilter" size="small">
                <el-radio-button label="all">全部</el-radio-button>
                <el-radio-button label="selected" :disabled="!selectedGroup">
                  当前分组{{ selectedGroup ? `：${selectedGroup.name}` : '' }}
                </el-radio-button>
                <el-radio-button label="ungrouped">未分组</el-radio-button>
              </el-radio-group>
              <el-button size="small" @click="loadDevices">刷新</el-button>
            </div>
          </template>

          <div class="move-bar">
            <span class="sel">已选 {{ selectedRows.length }} 台</span>
            <el-select v-model="targetGroupId" placeholder="目标分组" clearable size="small" style="width: 220px">
              <el-option
                v-for="g in groupOptions"
                :key="g.id"
                :label="`${g.label}（${g.count}）`"
                :value="g.id"
              />
            </el-select>
            <el-button
              v-if="auth.can('operator')"
              type="primary"
              size="small"
              :disabled="!selectedRows.length || targetGroupId == null"
              @click="moveDevices(targetGroupId)"
              >移动到分组</el-button
            >
            <el-button v-if="auth.can('operator')" size="small" :disabled="!selectedRows.length" @click="moveDevices(0)">取消分组</el-button>
          </div>

          <el-table
            :data="filteredDevices"
            v-loading="devLoading"
            border
            stripe
            size="small"
            height="calc(100vh - 260px)"
            @selection-change="onSelectionChange"
          >
            <el-table-column type="selection" width="44" />
            <el-table-column prop="id" label="ID" width="64" />
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="statusType[row.status]" size="small">{{ statusText[row.status] }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="当前分组" min-width="140">
              <template #default="{ row }">
                <el-tag v-if="row.group_id != null" size="small" effect="plain">{{ groupName(row.group_id) }}</el-tag>
                <span v-else class="muted">未分组</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.page {
  padding: 16px;
}
.card {
  border: 1px solid #ebeef5;
}
.card-hd {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.spacer {
  flex: 1;
}
.hint {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.tip {
  color: var(--color-text-muted);
  font-size: 12px;
}
.tree-node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding-right: 8px;
}
.tree-name {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cnt {
  transform: scale(0.9);
}
.total {
  color: var(--color-text-muted);
  font-size: 12px;
}
.tree-ops {
  opacity: 0;
  transition: opacity 0.15s;
}
.tree-node:hover .tree-ops {
  opacity: 1;
}
.move-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.sel {
  color: var(--color-text-secondary);
  font-size: 13px;
}
.muted {
  color: #c0c4cc;
}
</style>
