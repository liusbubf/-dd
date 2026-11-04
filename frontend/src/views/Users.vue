<script setup>
import { onMounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'

const auth = useAuth()

const ROLE_LEVELS = { viewer: 1, operator: 2, admin: 3, superadmin: 4 }
const roleLabels = {
  superadmin: '超级管理员',
  admin: '管理员',
  operator: '操作员',
  viewer: '查看员',
}
const roleTag = { superadmin: 'danger', admin: 'warning', operator: 'success', viewer: 'info' }
const roleOptions = [
  { value: 'viewer', label: '查看员' },
  { value: 'operator', label: '操作员' },
  { value: 'admin', label: '管理员' },
  { value: 'superadmin', label: '超级管理员' },
]

const canManage = computed(() => (ROLE_LEVELS[auth.user?.role] || 0) >= ROLE_LEVELS.admin)

const users = ref([])
const loading = ref(false)

const createDlg = ref(false)
const saving = ref(false)
const form = ref({ username: '', password: '', role: 'viewer' })

const roleDlg = ref(false)
const editing = ref(null)
const editRole = ref('viewer')

const banDlg = ref(false)
const banning = ref(null)
const banReason = ref('')

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/users')
    users.value = data
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (canManage.value) load()
})

function openCreate() {
  form.value = { username: '', password: '', role: 'viewer' }
  createDlg.value = true
}

async function createUser() {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请填写用户名和密码')
    return
  }
  saving.value = true
  try {
    await api.post('/users', form.value)
    ElMessage.success('用户已创建')
    createDlg.value = false
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  } finally {
    saving.value = false
  }
}

function openRole(u) {
  editing.value = u
  editRole.value = u.role
  roleDlg.value = true
}

async function saveRole() {
  try {
    await api.patch(`/users/${editing.value.id}`, { role: editRole.value })
    ElMessage.success('角色已更新')
    roleDlg.value = false
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '更新失败')
  }
}

async function resetPwd(u) {
  try {
    const { value } = await ElMessageBox.prompt(`为「${u.username}」设置新密码`, '重置密码', {
      inputType: 'password',
      inputValidator: (v) => (v && v.length >= 4 ? true : '密码至少 4 位'),
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
    await api.patch(`/users/${u.id}`, { password: value })
    ElMessage.success('密码已重置')
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function removeUser(u) {
  try {
    await ElMessageBox.confirm(`确认删除用户「${u.username}」？`, '确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await api.delete(`/users/${u.id}`)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

function openBan(u) {
  banning.value = u
  banReason.value = ''
  banDlg.value = true
}

async function banUser() {
  if (!banReason.value.trim()) {
    ElMessage.warning('请输入封禁原因')
    return
  }
  try {
    await http.banUser(banning.value.id, { reason: banReason.value })
    ElMessage.success('用户已封禁')
    banDlg.value = false
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '封禁失败')
  }
}

async function unbanUser(u) {
  try {
    await ElMessageBox.confirm(`确认解封用户「${u.username}」？`, '确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await http.unbanUser(u.id)
    ElMessage.success('用户已解封')
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '解封失败')
  }
}

function fmt(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString('zh-CN')
}
</script>

<template>
  <div class="page">
    <el-alert
      v-if="!canManage"
      type="warning"
      :closable="false"
      show-icon
      title="需要管理员权限"
      description="当前账号无权访问用户管理，请联系管理员分配「管理员」及以上角色。"
    />
    <template v-else>
      <div class="toolbar">
        <el-button type="primary" @click="openCreate">新建用户</el-button>
        <div class="spacer"></div>
        <el-button @click="load">刷新</el-button>
      </div>

      <el-table :data="users" v-loading="loading" border stripe style="width: 100%" size="small">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" label="用户名" min-width="160" />
        <el-table-column label="角色" width="140">
          <template #default="{ row }">
            <el-tag :type="roleTag[row.role]" size="small">{{ roleLabels[row.role] || row.role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.is_banned" type="danger" size="small">已封禁</el-tag>
            <el-tag v-else type="success" size="small">正常</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="封禁原因" min-width="180">
          <template #default="{ row }">{{ row.banned_reason || '—' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="180">
          <template #default="{ row }">{{ fmt(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="360" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openRole(row)">改角色</el-button>
            <el-button size="small" @click="resetPwd(row)">重置密码</el-button>
            <el-button v-if="row.is_banned" size="small" type="success" @click="unbanUser(row)">解封</el-button>
            <el-button v-else size="small" type="warning" @click="openBan(row)">封禁</el-button>
            <el-button size="small" type="danger" @click="removeUser(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <!-- 新建用户 -->
    <el-dialog v-model="createDlg" title="新建用户" width="420px">
      <el-form label-width="80px">
        <el-form-item label="用户名"><el-input v-model="form.username" placeholder="登录用户名" /></el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password placeholder="初始密码" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%">
            <el-option v-for="r in roleOptions" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createUser">创建</el-button>
      </template>
    </el-dialog>

    <!-- 修改角色 -->
    <el-dialog v-model="roleDlg" title="修改角色" width="380px">
      <el-form label-width="80px">
        <el-form-item label="用户名"><span>{{ editing?.username }}</span></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="editRole" style="width: 100%">
            <el-option v-for="r in roleOptions" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleDlg = false">取消</el-button>
        <el-button type="primary" @click="saveRole">保存</el-button>
      </template>
    </el-dialog>

    <!-- 封禁用户 -->
    <el-dialog v-model="banDlg" title="封禁用户" width="420px">
      <el-form label-width="80px">
        <el-form-item label="用户名"><span>{{ banning?.username }}</span></el-form-item>
        <el-form-item label="封禁原因">
          <el-input v-model="banReason" type="textarea" :rows="3" placeholder="请输入封禁原因" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="banDlg = false">取消</el-button>
        <el-button type="danger" @click="banUser">确认封禁</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  padding: 16px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.spacer {
  flex: 1;
}
</style>
