<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'
import { useDevices } from '../stores/devices'

const auth = useAuth()
const store = useDevices()

const items = ref([])
const statusFilter = ref('')
const keyword = ref('')
const loading = ref(false)

const dlg = ref(false)
const editing = ref(null)
const form = ref({ ip: '', port: 8888, username: '', password: '', status: 'available', group_name: '', note: '', expires_at: '' })

const bindDlg = ref(false)
const bindTarget = ref(null)
const bindDeviceId = ref(null)
const applyFingerprint = ref(true)

const statusType = { available: 'success', in_use: 'warning', disabled: 'info' }
const statusText = { available: '可用', in_use: '使用中', disabled: '已停用' }

const devicesList = computed(() => store.list)

async function load() {
  loading.value = true
  try {
    const r = await api.listIps({
      status: statusFilter.value || undefined,
      q: keyword.value || undefined,
    })
    items.value = r.data.items
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || 'IP 资源加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.value = { ip: '', port: 8888, username: '', password: '', status: 'available', group_name: '', note: '', expires_at: '' }
  dlg.value = true
}

function openEdit(row) {
  editing.value = row
  form.value = {
    ip: row.ip,
    port: row.port,
    username: row.username,
    password: row.password || '',
    status: row.status,
    group_name: row.group_name,
    note: row.note,
    expires_at: row.expires_at ? new Date(row.expires_at).toISOString().slice(0, 16) : '',
  }
  dlg.value = true
}

async function save() {
  if (!form.value.ip.trim()) return ElMessage.warning('请填写 IP')
  const payload = {
    ip: form.value.ip.trim(),
    port: Number(form.value.port) || 0,
    username: form.value.username,
    status: form.value.status,
    group_name: form.value.group_name,
    note: form.value.note,
    expires_at: form.value.expires_at ? new Date(form.value.expires_at.replace(' ', 'T')).toISOString() : null,
  }
  // 掩码口令不回写：只有用户输入了真实口令才带上
  if (form.value.password && !form.value.password.includes('****')) payload.password = form.value.password
  try {
    if (editing.value) await api.updateIp(editing.value.id, payload)
    else await api.createIp(payload)
    ElMessage.success(editing.value ? '已更新' : '已新增')
    dlg.value = false
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail?.[0]?.msg || e?.response?.data?.detail || '保存失败')
  }
}

async function testOne(row) {
  row._testing = true
  try {
    const r = await api.testIp(row.id)
    if (r.data.ok) ElMessage.success(r.data.detail)
    else ElMessage.error(r.data.detail)
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '探测失败')
  } finally {
    row._testing = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确定删除 IP ${row.ip}:${row.port}？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await api.deleteIp(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

function openBind(row) {
  bindTarget.value = row
  bindDeviceId.value = null
  applyFingerprint.value = true
  bindDlg.value = true
  if (!store.list.length) store.refresh().catch(() => {})
}

async function doBind() {
  if (!bindDeviceId.value) return ElMessage.warning('请选择目标云机')
  try {
    await api.bindIp(bindTarget.value.id, {
      device_id: bindDeviceId.value,
      apply_to_fingerprint: applyFingerprint.value,
    })
    ElMessage.success('绑定成功')
    bindDlg.value = false
    await load()
    store.refresh().catch(() => {})
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '绑定失败')
  }
}

async function unbind(row, deviceId) {
  try {
    await api.unbindIp(row.id, { device_id: deviceId })
    ElMessage.success('已解绑')
    await load()
    store.refresh().catch(() => {})
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '解绑失败')
  }
}

async function unbindByPick(row) {
  const bound = devicesList.value.filter((d) => d.ip_id === row.id)
  if (!bound.length) return ElMessage.info('该 IP 当前没有已绑定的云机（可在「设备」里查看 ip_id）')
  const { value } = await ElMessageBox.prompt(
    `已绑定云机：${bound.map((d) => `#${d.id} ${d.name}`).join('、')}。请输入要解绑的云机编号`,
    '解绑 IP',
    { inputPlaceholder: String(bound[0].id) },
  ).catch(() => ({ value: null }))
  if (!value) return
  await unbind(row, Number(value))
}

onMounted(() => {
  load()
  if (!store.list.length) store.refresh().catch(() => {})
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-select v-model="statusFilter" style="width: 130px" placeholder="全部状态" clearable @change="load">
        <el-option label="可用" value="available" />
        <el-option label="使用中" value="in_use" />
        <el-option label="已停用" value="disabled" />
      </el-select>
      <el-input v-model="keyword" placeholder="搜索 IP" clearable style="width: 200px" @keyup.enter="load" />
      <el-button @click="load">查询</el-button>
      <div style="flex: 1"></div>
      <el-button v-if="auth.can('operator')" type="primary" @click="openCreate">新增 IP 资源</el-button>
    </div>

    <el-table v-loading="loading" :data="items" border stripe size="small">
      <el-table-column prop="id" label="#" width="60" />
      <el-table-column label="IP" min-width="150">
        <template #default="{ row }"><span class="mono">{{ row.ip }}</span></template>
      </el-table-column>
      <el-table-column prop="port" label="端口" width="80" />
      <el-table-column prop="username" label="账号" width="110" show-overflow-tooltip />
      <el-table-column label="口令" width="100">
        <template #default="{ row }">{{ row.has_password ? row.password : '—' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="statusType[row.status]" effect="plain">{{ statusText[row.status] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="group_name" label="分组" width="100" show-overflow-tooltip />
      <el-table-column label="到期" width="150">
        <template #default="{ row }">{{ row.expires_at ? new Date(row.expires_at).toLocaleString() : '—' }}</template>
      </el-table-column>
      <el-table-column label="探测结果" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">
          <el-tag v-if="row.test_result !== 'unknown'" size="small" :type="row.test_result === 'ok' ? 'success' : 'danger'" effect="plain">
            {{ row.test_result === 'ok' ? '连通' : '失败' }}
          </el-tag>
          <span class="detail">{{ row.test_detail || '未探测' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :loading="row._testing" @click="testOne(row)">测试</el-button>
          <template v-if="auth.can('operator')">
            <el-button size="small" type="primary" plain @click="openBind(row)">绑定</el-button>
            <el-button size="small" plain @click="unbindByPick(row)">解绑</el-button>
            <el-button size="small" plain @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dlg" :title="editing ? '编辑 IP 资源' : '新增 IP 资源'" width="560px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="IP">
          <el-input v-model="form.ip" placeholder="例如 1.2.3.4" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number v-model="form.port" :min="0" :max="65535" />
          <span class="hint">0 表示不配置端口（无法做 TCP 探测）</span>
        </el-form-item>
        <el-form-item label="账号">
          <el-input v-model="form.username" placeholder="代理账号（可空）" />
        </el-form-item>
        <el-form-item label="口令">
          <el-input v-model="form.password" placeholder="代理口令（可空，接口只回显掩码）" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 160px">
            <el-option label="可用" value="available" />
            <el-option label="使用中" value="in_use" />
            <el-option label="已停用" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item label="分组">
          <el-input v-model="form.group_name" placeholder="例如 hk / us" />
        </el-form-item>
        <el-form-item label="到期时间">
          <el-input v-model="form.expires_at" placeholder="YYYY-MM-DD HH:mm，可空" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bindDlg" title="绑定 IP 到云机" width="520px">
      <el-form label-width="90px">
        <el-form-item label="IP">
          <span class="mono">{{ bindTarget?.ip }}:{{ bindTarget?.port }}</span>
        </el-form-item>
        <el-form-item label="目标云机">
          <el-select v-model="bindDeviceId" filterable placeholder="选择云机" style="width: 260px">
            <el-option v-for="d in devicesList" :key="d.id" :label="`#${d.id} ${d.name}`" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="">
          <el-checkbox v-model="applyFingerprint">同时写入设备指纹（exit_ip / proxy）</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindDlg = false">取消</el-button>
        <el-button type="primary" @click="doBind">绑定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.mono {
  font-family: Consolas, monospace;
}
.detail {
  margin-left: 6px;
  color: var(--color-text-muted);
  font-size: 12px;
}
.hint {
  margin-left: 8px;
  color: var(--color-text-muted);
  font-size: 12px;
}
</style>
