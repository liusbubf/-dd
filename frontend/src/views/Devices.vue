<script setup>
import { onMounted, onActivated, onDeactivated, onBeforeUnmount, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'
import { useDevices, SKIN_PHASE_TEXT, RENEW_PHASE_TEXT } from '../stores/devices'
import DeviceCard from '../components/DeviceCard.vue'
import StateBlock from '../components/StateBlock.vue'
import FloatingPlayer from '../components/FloatingPlayer.vue'

const auth = useAuth()

defineOptions({ name: 'Devices' })

const store = useDevices()
const router = useRouter()

const filter = ref({ q: '', status: '', group_id: '' })
const viewMode = ref(localStorage.getItem('devices.viewMode') === 'card' ? 'card' : 'table')
function setViewMode(mode) {
  viewMode.value = mode
  localStorage.setItem('devices.viewMode', mode)
}
function toggleCardSelect(d) {
  const i = selectedIds.value.indexOf(d.id)
  if (i >= 0) selectedIds.value.splice(i, 1)
  else selectedIds.value.push(d.id)
}
const selectedIds = ref([])
const createDlg = ref(false)
const fpDlg = ref(false)
const fpDevice = ref(null)
const creating = ref(false)
const loading = ref(false)
const isFirstLoad = ref(true)
const checking = ref(false)

// 一键换肤
const skinDlg = ref(false)
const skinThemes = ref([])
const skinForm = ref({ theme: 'ios', scope: 'all' })
const skinning = ref(false)

// 一键新机
const renewDlg = ref(false)
const renewTargets = ref([])
const renewForm = ref({ mode: 'hard', rotate_proxy: false, keep_url: false })
const renewing = ref(false)

// 设备快照
const snapDlg = ref(false)
const snapDevice = ref(null)
const snapshots = ref([])
const snapLoading = ref(false)
const snapCreating = ref(false)
const snapBusyId = ref(null)
const snapName = ref('')

// 重置两入口（V3）：恢复到快照 / 清空数据（保留设备），两者都必须输入设备名二次确认
const resetDlg = ref(false)
const resetMode = ref('wipe') // restore_snapshot | wipe
const resetDevice = ref(null)
const resetName = ref('')
const resetBusy = ref(false)
const resetTitle = computed(() =>
  resetMode.value === 'restore_snapshot' ? '恢复到快照（最近一次可用快照）' : '清空数据（保留设备）',
)
const resetSubmitText = computed(() =>
  resetMode.value === 'restore_snapshot' ? '确认恢复' : '确认清空',
)

// 实体机接入
const backendName = ref('simulator')
const isPhysical = computed(() => backendName.value === 'physical')
const adbDlg = ref(false)
const adbDevices = ref([])
const adbError = ref('')
const adbLoading = ref(false)
const adoptingSerial = ref('')
const form = ref({
  count: 10,
  name_prefix: '演示机',
  group_id: null,
  width: 720,
  height: 1280,
  dpi: 320,
  target_url: 'https://browserleaks.com',
  auto_start: true,
  fingerprint_mode: 'commercial',
  region: 'global',
})
const fingerprintPolicies = ref([])

// ---------- 工具栏（V1-3）：显示 IP / 排序 / 设备树 ----------
const showIp = ref(localStorage.getItem('devices.showIp') !== 'off')
function setShowIp(v) {
  localStorage.setItem('devices.showIp', v ? 'on' : 'off')
}
const sortBy = ref(localStorage.getItem('devices.sortBy') || 'auto')
function setSortBy(v) {
  localStorage.setItem('devices.sortBy', v)
}
const treeCollapsed = ref(localStorage.getItem('devices.treeCollapsed') === '1')
function toggleTree() {
  treeCollapsed.value = !treeCollapsed.value
  localStorage.setItem('devices.treeCollapsed', treeCollapsed.value ? '1' : '0')
}

const groupTree = ref([])
const ungroupedCount = ref(0)
const groupFilter = ref({ ids: null, ungrouped: false, label: '全部设备' })

function groupNodes(list) {
  return (list || []).map((g) => ({
    id: g.id,
    name: g.name,
    count: g.total_count ?? g.device_count ?? 0,
    label: `${g.name} (${g.total_count ?? g.device_count ?? 0})`,
    children: groupNodes(g.children),
  }))
}
const treeNodes = computed(() => [
  {
    id: -1,
    label: `全部设备 (${store.list.length})`,
    children: [
      ...groupNodes(groupTree.value),
      { id: 0, label: `未分组 (${ungroupedCount.value})` },
    ],
  },
])

async function loadTree() {
  try {
    const { data } = await api.groupTree()
    groupTree.value = data.roots || data.items || []
    ungroupedCount.value = data.ungrouped_count || 0
  } catch {
    groupTree.value = []
    ungroupedCount.value = 0
  }
}

function subtreeIds(node) {
  const ids = [node.id]
  const walk = (kids) => {
    ;(kids || []).forEach((k) => {
      ids.push(k.id)
      walk(k.children)
    })
  }
  walk(node.children)
  return ids
}

function onTreeClick(node) {
  filter.value.group_id = ''
  if (node.id === -1) {
    groupFilter.value = { ids: null, ungrouped: false, label: '全部设备' }
  } else if (node.id === 0) {
    groupFilter.value = { ids: null, ungrouped: true, label: '未分组' }
  } else {
    groupFilter.value = { ids: subtreeIds(node), ungrouped: false, label: node.name }
  }
}

function groupName(id) {
  let found = ''
  const walk = (list) =>
    (list || []).forEach((g) => {
      if (g.id === id) found = g.name
      walk(g.children)
    })
  walk(groupTree.value)
  return found
}

const filtered = computed(() =>
  store.list.filter((d) => {
    if (filter.value.status && d.status !== filter.value.status) return false
    if (filter.value.group_id && d.group_id !== filter.value.group_id) return false
    if (groupFilter.value.ungrouped && d.group_id != null) return false
    if (groupFilter.value.ids && !groupFilter.value.ids.includes(d.group_id)) return false
    if (filter.value.q && !d.name.includes(filter.value.q)) return false
    return true
  }),
)

const displayed = computed(() => {
  const list = [...filtered.value]
  if (sortBy.value === 'name') {
    list.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
  } else if (sortBy.value === 'online') {
    list.sort((a, b) => (a.status === 'running' ? 0 : 1) - (b.status === 'running' ? 0 : 1) || a.id - b.id)
  } else if (sortBy.value === 'group') {
    list.sort((a, b) => groupName(a.group_id).localeCompare(groupName(b.group_id), 'zh-CN') || a.id - b.id)
  } else if (sortBy.value === 'remaining') {
    list.sort((a, b) => {
      const ra = typeof a.remaining_seconds === 'number' ? a.remaining_seconds : 1e12
      const rb = typeof b.remaining_seconds === 'number' ? b.remaining_seconds : 1e12
      return ra - rb
    })
  } else {
    // auto：运行中优先，其次剩余时长少的优先（快到期先处理）
    list.sort((a, b) => {
      const runA = a.status === 'running' ? 0 : 1
      const runB = b.status === 'running' ? 0 : 1
      if (runA !== runB) return runA - runB
      const ra = typeof a.remaining_seconds === 'number' ? a.remaining_seconds : 1e12
      const rb = typeof b.remaining_seconds === 'number' ? b.remaining_seconds : 1e12
      return ra - rb || a.id - b.id
    })
  }
  return list
})

// ---------- 右键菜单 ----------
const ctx = ref({ visible: false, x: 0, y: 0, device: null })
function openCtx(e, d) {
  e.preventDefault()
  ctx.value = {
    visible: true,
    x: Math.min(e.clientX, window.innerWidth - 180),
    y: Math.min(e.clientY, window.innerHeight - 200),
    device: d,
  }
}
function closeCtx() {
  ctx.value.visible = false
}

async function ctxAction(action) {
  const d = ctx.value.device
  ctx.value.visible = false
  if (!d) return
  if (action === 'restart') {
    await act(api.restartDevice, d.id, '已下发重启')
  } else if (action === 'shot') {
    takeShot(d)
  } else if (action === 'restore') {
    openReset('restore_snapshot', d)
  } else if (action === 'wipe') {
    openReset('wipe', d)
  } else if (action === 'detail') {
    router.push(`/detail/${d.id}?from=devices`)
  } else if (action === 'move') {
    openMove(d)
  } else if (action === 'bind') {
    openBindIp(d)
  }
}

// 移组
const moveDlg = ref(false)
const moveDevice = ref(null)
const moveGroupId = ref(null)
const moving = ref(false)
function openMove(d) {
  moveDevice.value = d
  moveGroupId.value = d.group_id || 0
  moveDlg.value = true
}
async function submitMove() {
  if (!moveDevice.value) return
  moving.value = true
  try {
    await api.moveGroupDevices(moveGroupId.value || 0, { device_ids: [moveDevice.value.id] })
    ElMessage.success(moveGroupId.value ? '已移入分组' : '已移出分组')
    moveDlg.value = false
    await loadAll()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '移组失败')
  } finally {
    moving.value = false
  }
}

// 绑定 IP
const bindDlg = ref(false)
const bindDevice = ref(null)
const bindIps = ref([])
const bindIpId = ref(null)
const bindLoading = ref(false)
const binding = ref(false)
const bindError = ref('')
async function openBindIp(d) {
  bindDevice.value = d
  bindIpId.value = d.ip_id || null
  bindError.value = ''
  bindDlg.value = true
  bindLoading.value = true
  try {
    const { data } = await api.listIps({ status: 'available', limit: 200 })
    bindIps.value = data.items || []
  } catch (e) {
    bindError.value = e?.response?.data?.detail || 'IP 资源加载失败'
    bindIps.value = []
  } finally {
    bindLoading.value = false
  }
}
async function submitBind() {
  if (!bindIpId.value || !bindDevice.value) return
  binding.value = true
  try {
    await api.bindIp(bindIpId.value, { device_id: bindDevice.value.id, apply_to_fingerprint: true })
    ElMessage.success('IP 绑定成功')
    bindDlg.value = false
    await loadAll()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '绑定失败')
  } finally {
    binding.value = false
  }
}

async function loadAll() {
  await Promise.all([
    store.refresh(),
    store.refreshGroups(),
    store.refreshSkinApplying(),
    store.refreshRenewing(),
    loadTree(),
    loadBackendInfo(),
  ])
  loadExpiring()
}

const expiring = ref([])
async function loadExpiring() {
  try {
    const r = await api.listExpiring(24)
    expiring.value = r.data.devices || []
  } catch {
    expiring.value = []
  }
}

function fmtRemaining(sec) {
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  if (d > 0) return `剩余 ${d} 天 ${h} 小时`
  const m = Math.floor((sec % 3600) / 60)
  return d === 0 && h > 0 ? `剩余 ${h} 小时 ${m} 分` : `剩余 ${m} 分`
}

function remainingText(row) {
  if (typeof row.remaining_seconds === 'number') {
    return row.remaining_seconds > 0 ? fmtRemaining(row.remaining_seconds) : '已到期'
  }
  if (row.expires_at) {
    const ms = new Date(row.expires_at).getTime() - Date.now()
    return ms > 0 ? fmtRemaining(Math.floor(ms / 1000)) : '已到期'
  }
  return '未设置'
}

async function setExpiry(d) {
  const current = d.expires_at ? new Date(d.expires_at).toISOString().slice(0, 16) : ''
  try {
    const { value } = await ElMessageBox.prompt(
      '输入到期时间（YYYY-MM-DD HH:mm，留空表示清除）',
      `设置到期 · ${d.name}`,
      { inputValue: current, inputPlaceholder: '2026-12-31 18:00' },
    )
    const trimmed = (value || '').trim()
    const iso = trimmed ? new Date(trimmed.replace(' ', 'T')).toISOString() : null
    if (trimmed && Number.isNaN(new Date(trimmed.replace(' ', 'T')).getTime())) {
      ElMessage.error('时间格式不正确')
      return
    }
    await api.updateDevice(d.id, { expires_at: iso })
    ElMessage.success(iso ? '到期时间已更新' : '已清除到期时间')
    await loadAll()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e?.response?.data?.detail || '设置失败')
  }
}

async function loadBackendInfo() {
  try {
    const r = await api.discoverDevices()
    backendName.value = r.data.backend || 'simulator'
    adbDevices.value = r.data.devices || []
    adbError.value = r.data.error || ''
  } catch {
    // 扫描失败不影响设备列表展示
  }
}

function openAdbDialog() {
  adbDlg.value = true
  scanAdb()
}

async function scanAdb() {
  adbLoading.value = true
  adbError.value = ''
  try {
    const r = await api.discoverDevices()
    backendName.value = r.data.backend || backendName.value
    adbDevices.value = r.data.devices || []
    adbError.value = r.data.error || ''
  } catch (e) {
    adbError.value = e?.response?.data?.detail || '扫描失败'
  } finally {
    adbLoading.value = false
  }
}

async function adoptRow(d) {
  const { value } = await ElMessageBox.prompt('设备名称', '接入实体机', {
    inputValue: d.model || d.serial,
    confirmButtonText: '接入',
  })
  adoptingSerial.value = d.serial
  try {
    await api.adoptDevice({ serial: d.serial, name: value })
    ElMessage.success('实体机已接入')
    await store.refresh()
    await store.refreshGroups()
    await scanAdb()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '接入失败')
  } finally {
    adoptingSerial.value = ''
  }
}

async function loadSkinThemes() {
  try {
    skinThemes.value = (await api.listSkinThemes()).data.themes
  } catch {
    skinThemes.value = [{ key: 'ios', label: 'iOS 风' }]
  }
}

async function loadFingerprintPolicies() {
  try {
    const r = await api.listFingerprintPolicies()
    fingerprintPolicies.value = r.data.policies || []
    if (!fingerprintPolicies.value.some((p) => p.mode === form.value.fingerprint_mode)) {
      form.value.fingerprint_mode = 'commercial'
    }
  } catch {
    fingerprintPolicies.value = []
  }
}

let pollTimers = []
function startPolling() {
  stopPolling()
  pollTimers = [
    setInterval(() => store.refresh(), 5000),
    setInterval(() => store.refreshSkinApplying(), 5000),
    setInterval(() => store.refreshRenewing(), 5000),
    setInterval(() => store.refreshGroups(), 30000),
  ]
}
function stopPolling() {
  pollTimers.forEach((t) => clearInterval(t))
  pollTimers = []
}

onMounted(() => {
  // 缓存优先：store 已有数据时不显示 loading，后台静默刷新
  const hasCache = store.list.length > 0 || store.groups.length > 0
  loading.value = !hasCache
  Promise.all([loadAll(), loadSkinThemes(), loadFingerprintPolicies()]).finally(() => {
    loading.value = false
    isFirstLoad.value = false
  })
  startPolling()
  window.addEventListener('click', closeCtx)
})

onActivated(() => {
  if (isFirstLoad.value) return
  // keep-alive 返回：静默刷新（不设置 loading），保持表格渲染状态，并重启轮询
  loadAll()
  loadSkinThemes()
  loadFingerprintPolicies()
  startPolling()
})

onDeactivated(stopPolling)
onBeforeUnmount(() => {
  stopPolling()
  window.removeEventListener('click', closeCtx)
})

const skinLabel = (k) => {
  if (!k) return '原生安卓'
  return skinThemes.value.find((t) => t.key === k)?.label || k
}

async function applySkinRow(id, theme) {
  try {
    await api.applySkin(id, theme)
    ElMessage.success(`已换肤：${skinLabel(theme)} · 真机后台落地中，进度见「皮肤」列`)
    await store.refresh()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '换肤失败')
  }
}

async function applySkinBatch() {
  skinning.value = true
  try {
    const ids = skinForm.value.scope === 'filtered' ? filtered.value.map((d) => d.id) : []
    const r = await api.applySkinBatch(ids, skinForm.value.theme)
    ElMessage.success(
      `已为 ${r.data.count} 台设备换肤：${skinLabel(skinForm.value.theme)} · 真机逐台落地中，进度见「皮肤」列`,
    )
    skinDlg.value = false
    await store.refresh()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '换肤失败')
  } finally {
    skinning.value = false
  }
}

function openRenew(rows) {
  const list = Array.isArray(rows) ? rows : [rows]
  if (!list.length) {
    ElMessage.warning('请先勾选要新机的设备')
    return
  }
  if (isPhysical.value) {
    ElMessage.info('实体机的「清空数据（保留设备）」请使用设备行内入口')
    return
  }
  renewTargets.value = list
  renewForm.value = { mode: 'hard', rotate_proxy: false, keep_url: false }
  renewDlg.value = true
}

async function submitRenew() {
  if (!renewTargets.value.length) return
  renewing.value = true
  try {
    const ids = renewTargets.value.map((d) => d.id)
    const body = { ...renewForm.value }
    const r = ids.length === 1
      ? await api.renewDevice(ids[0], body)
      : await api.batchRenew(ids, body)
    const queued = r.data.queued ?? ids.length
    const skipped = (r.data.skipped || []).length
    const missing = (r.data.missing || []).length
    ElMessage.success(
      `已加入新机队列：${queued} 台${skipped ? `，跳过 ${skipped} 台（进行中）` : ''}${missing ? `，${missing} 台不存在` : ''} · 进度见「状态」列`,
    )
    renewDlg.value = false
    selectedIds.value = []
    await store.refresh()
    await store.refreshRenewing()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '一键新机失败')
  } finally {
    renewing.value = false
  }
}

const snapStatusText = { creating: '创建中', ready: '可用', restoring: '恢复中', error: '失败' }
const snapStatusType = { creating: 'warning', ready: 'success', restoring: 'warning', error: 'danger' }

function fmtSize(n) {
  if (n === null || n === undefined) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 ** 3) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function fmtTime(t) {
  if (!t) return '—'
  const d = new Date(t)
  return Number.isNaN(d.getTime()) ? t : d.toLocaleString()
}

async function openSnaps(row) {
  snapDevice.value = row
  snapshots.value = []
  snapName.value = ''
  snapDlg.value = true
  await loadSnapshots()
}

async function loadSnapshots() {
  if (!snapDevice.value) return
  snapLoading.value = true
  try {
    const r = await api.listSnapshots(snapDevice.value.id)
    snapshots.value = r.data
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载快照失败')
  } finally {
    snapLoading.value = false
  }
}

async function createSnap() {
  if (!snapDevice.value) return
  snapCreating.value = true
  try {
    await api.createSnapshot(snapDevice.value.id, snapName.value.trim())
    ElMessage.success('快照创建成功')
    snapName.value = ''
    await loadSnapshots()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '快照创建失败')
    await loadSnapshots()
  } finally {
    snapCreating.value = false
  }
}

async function restoreSnap(s) {
  let confirmName
  try {
    const { value } = await ElMessageBox.prompt(
      `将用快照「${s.name || `#${s.id}`}」覆盖设备当前全部数据并重启，设备记录不变。\n请输入设备名「${snapDevice.value.name}」确认：`,
      '恢复到快照',
      {
        type: 'warning',
        confirmButtonText: '恢复',
        inputPlaceholder: snapDevice.value.name,
        inputValidator: (v) => (v || '').trim() === snapDevice.value.name || '设备名不匹配',
      },
    )
    confirmName = (value || '').trim()
  } catch {
    return
  }
  snapBusyId.value = s.id
  try {
    await api.restoreSnapshot(snapDevice.value.id, s.id, confirmName)
    ElMessage.success('快照已恢复，设备正在重启')
    await store.refresh()
    await loadSnapshots()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '恢复失败')
    await loadSnapshots()
  } finally {
    snapBusyId.value = null
  }
}

function openReset(mode, d) {
  if (!d) return
  if (mode === 'restore_snapshot' && isPhysical.value) {
    ElMessage.warning('实体机不支持快照；请使用「清空数据（保留设备）」')
    return
  }
  resetMode.value = mode
  resetDevice.value = d
  resetName.value = ''
  resetDlg.value = true
}

async function submitReset() {
  if (!resetDevice.value) return
  const name = resetName.value.trim()
  if (name !== resetDevice.value.name) {
    ElMessage.warning('请输入完整的设备名称以确认')
    return
  }
  resetBusy.value = true
  try {
    if (resetMode.value === 'restore_snapshot') {
      await api.restoreLatestSnapshot(resetDevice.value.id, name)
      ElMessage.success('已恢复到最近一次可用快照，设备正在重启')
    } else {
      await api.wipeDeviceData(resetDevice.value.id, name)
      ElMessage.success('设备数据已清空并重启；设备记录与绑定关系已保留')
    }
    resetDlg.value = false
    await store.refresh()
    if (snapDlg.value) await loadSnapshots()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败，未做假成功')
  } finally {
    resetBusy.value = false
  }
}

async function deleteSnap(s) {
  await ElMessageBox.confirm(`删除快照「${s.name || `#${s.id}`}」？`, '删除快照', { type: 'warning' })
  snapBusyId.value = s.id
  try {
    await api.deleteSnapshot(snapDevice.value.id, s.id)
    ElMessage.success('快照已删除')
    await loadSnapshots()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  } finally {
    snapBusyId.value = null
  }
}

async function claimRow(d) {
  try {
    await api.claimDevice(d.id)
    ElMessage.success(`已占用「${d.name}」`)
    await store.refresh()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '占用失败')
  }
}

async function releaseRow(d) {
  try {
    await api.releaseDevice(d.id)
    ElMessage.success(`已释放「${d.name}」`)
    await store.refresh()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '释放失败')
  }
}

async function checkAll() {
  checking.value = true
  try {
    const r = await api.checkDevices()
    const d = r.data
    ElMessage.success(
      `巡检完成：在线 ${d.healthy} 台，离线 ${d.unhealthy} 台，状态更新 ${d.changed} 台${d.skipped ? `，跳过 ${d.skipped} 台` : ''}`,
    )
    await store.refresh()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '巡检失败')
  } finally {
    checking.value = false
  }
}

async function batchCreate() {
  creating.value = true
  try {
    await api.batchCreate(form.value)
    ElMessage.success(`已创建 ${form.value.count} 台云手机`)
    createDlg.value = false
    await store.refresh()
    await store.refreshGroups()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

// 设备截图（预览 + 下载）
const shotDlg = ref(false)
const shotDevice = ref(null)
const shotFrame = ref('')
const shotLoading = ref(false)
const shootingId = ref(null)

// 浮窗投屏（V1-1 / V2 多实例）：与「操控（新页）」并存，入口在表格行与卡片上保持一致。
// 同时最多 3 个：每个浮窗 300ms 轮询一帧，开太多会把后端拉满。
const MAX_FLOATS = 3
const floats = ref([])
let floatSeq = 0
function openFloat(d) {
  if (floats.value.some((f) => f.device.id === d.id)) {
    ElMessage.info('该设备已在浮窗中')
    focusFloat(d.id)
    return
  }
  if (floats.value.length >= MAX_FLOATS) {
    ElMessage.warning(`浮窗最多同时打开 ${MAX_FLOATS} 个，请先关闭一个`)
    return
  }
  floats.value.push({ device: d, z: 1100 + floatSeq++ })
}
function closeFloat(id) {
  floats.value = floats.value.filter((f) => f.device.id !== id)
}
function focusFloat(id) {
  const f = floats.value.find((x) => x.device.id === id)
  if (f) f.z = 1100 + floatSeq++
}
function openPageFromFloat(d) {
  closeFloat(d.id)
  router.push(`/device/${d.id}?from=devices`)
}

async function moveToGroup(row, gid) {
  if ((row.group_id || 0) === gid) return
  try {
    await api.moveGroupDevices(gid, { device_ids: [row.id] })
    ElMessage.success(gid ? '已移动分组' : '已移出分组')
    await store.refresh()
    await store.refreshGroups()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '移动分组失败')
  }
}

async function takeShot(d) {
  shootingId.value = d.id
  try {
    const r = await api.screenshot(d.id)
    shotDevice.value = d
    shotFrame.value = r.data.frame
    shotDlg.value = true
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '截图失败')
  } finally {
    shootingId.value = null
  }
}

function downloadShot() {
  if (!shotFrame.value) return
  const a = document.createElement('a')
  a.href = shotFrame.value
  a.download = `${shotDevice.value?.name || 'device'}-${Date.now()}.png`
  a.click()
}

async function act(fn, id, okMsg) {
  try {
    await fn(id)
    if (okMsg) ElMessage.success(okMsg)
    await store.refresh()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function rename(d) {
  const { value } = await ElMessageBox.prompt('新名称', '重命名', { inputValue: d.name })
  await api.updateDevice(d.id, { name: value })
  await store.refresh()
  ElMessage.success('已重命名')
}

async function assignGroup(d, gid) {
  await api.updateDevice(d.id, { group_id: gid })
  await store.refresh()
  await store.refreshGroups()
}

async function remove(d) {
  await ElMessageBox.confirm(`删除设备「${d.name}」？`, '确认', { type: 'warning' })
  await act(api.deleteDevice, d.id, '已删除')
}

// 封禁/解封设备
const banDlg = ref(false)
const banning = ref(null)
const banReason = ref('')

function openBan(d) {
  banning.value = d
  banReason.value = ''
  banDlg.value = true
}

async function banDevice() {
  if (!banReason.value.trim()) {
    ElMessage.warning('请输入封禁原因')
    return
  }
  try {
    await api.banDevice(banning.value.id, { reason: banReason.value })
    ElMessage.success('设备已封禁')
    banDlg.value = false
    await store.refresh()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '封禁失败')
  }
}

async function unbanDevice(d) {
  try {
    await ElMessageBox.confirm(`确认解封设备「${d.name}」？`, '确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await api.unbanDevice(d.id)
    ElMessage.success('设备已解封')
    await store.refresh()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '解封失败')
  }
}

async function batchDelete() {
  if (!selectedIds.value.length) {
    ElMessage.warning('请先勾选要删除的设备')
    return
  }
  await ElMessageBox.confirm(`确认删除选中的 ${selectedIds.value.length} 台设备？`, '批量删除', { type: 'warning' })
  try {
    const r = await api.batchDelete(selectedIds.value)
    ElMessage.success(`已删除 ${r.data.count} 台设备`)
    selectedIds.value = []
    await store.refresh()
    await store.refreshGroups()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '批量删除失败')
  }
}

async function newGroup() {
  const { value } = await ElMessageBox.prompt('分组名称', '新建分组')
  await api.createGroup({ name: value })
  await store.refreshGroups()
  ElMessage.success('分组已创建')
}

function showFp(d) {
  fpDevice.value = d
  fpDlg.value = true
}

const statusType = { running: 'success', stopped: 'info', creating: 'warning', error: 'danger' }
const statusText = { running: '运行中', stopped: '已停止', creating: '创建中', error: '异常' }

const renewTagType = (phase) => (phase === 'done' ? 'success' : phase === 'failed' ? 'danger' : 'warning')
</script>

<template>
  <div class="page">
    <el-alert
      v-if="expiring.length"
      class="expire-alert"
      type="warning"
      show-icon
      :closable="false"
      :title="`有 ${expiring.length} 台设备将在 24 小时内到期：${expiring.map((d) => d.name).slice(0, 5).join('、')}${expiring.length > 5 ? ' 等' : ''}`"
    >
      <template #default>
        <span class="expire-sub">请及时续期，避免设备被回收。</span>
      </template>
    </el-alert>
    <div class="toolbar">
      <el-button v-if="!isPhysical && auth.can('operator')" type="primary" :icon="'Plus'" @click="createDlg = true">批量建机</el-button>
      <el-button v-else-if="auth.can('operator')" type="primary" :icon="'Link'" @click="openAdbDialog">接入实体机</el-button>
      <el-button v-if="auth.can('operator')" :icon="'FolderAdd'" @click="newGroup">新建分组</el-button>
      <el-button v-if="!isPhysical && auth.can('operator')" :icon="'MagicStick'" @click="skinDlg = true">一键换肤</el-button>
      <el-button
        v-if="!isPhysical && auth.can('operator')"
        type="warning"
        plain
        :icon="'RefreshRight'"
        :disabled="!selectedIds.length"
        @click="openRenew(store.list.filter((d) => selectedIds.includes(d.id)))"
      >
        一键新机{{ selectedIds.length ? ` (${selectedIds.length})` : '' }}
      </el-button>
      <el-button v-if="auth.can('operator')" type="danger" :icon="'Delete'" :disabled="!selectedIds.length" @click="batchDelete">
        批量删除{{ selectedIds.length ? ` (${selectedIds.length})` : '' }}
      </el-button>
      <el-divider direction="vertical" />
      <el-input v-model="filter.q" placeholder="搜索名称" style="width: 160px" clearable :prefix-icon="'Search'" />
      <el-select v-model="filter.status" placeholder="状态" clearable style="width: 120px">
        <el-option label="运行中" value="running" />
        <el-option label="已停止" value="stopped" />
        <el-option label="异常" value="error" />
      </el-select>
      <el-select v-model="filter.group_id" placeholder="分组" clearable style="width: 140px">
        <el-option v-for="g in store.groups" :key="g.id" :label="`${g.name} (${g.device_count})`" :value="g.id" />
      </el-select>
      <el-divider direction="vertical" />
      <el-button v-if="treeCollapsed" :icon="'Grid'" size="small" @click="toggleTree">设备树</el-button>
      <el-switch
        v-model="showIp"
        size="small"
        active-text="显示 IP"
        style="margin-right: var(--sp-2)"
        @change="setShowIp"
      />
      <el-select v-model="sortBy" size="small" style="width: 118px" @change="setSortBy">
        <el-option label="排序：默认" value="auto" />
        <el-option label="排序：在线优先" value="online" />
        <el-option label="排序：分组" value="group" />
        <el-option label="排序：剩余时长" value="remaining" />
        <el-option label="排序：名称" value="name" />
      </el-select>
      <div class="spacer"></div>
      <el-button v-if="auth.can('operator')" :icon="'Odometer'" :loading="checking" @click="checkAll">巡检</el-button>
      <el-button :icon="'Refresh'" @click="store.refresh()">刷新</el-button>
      <el-radio-group :model-value="viewMode" size="small" @change="setViewMode">
        <el-radio-button value="table">表格</el-radio-button>
        <el-radio-button value="card">卡片</el-radio-button>
      </el-radio-group>
    </div>

    <div class="devices-body">
      <aside v-if="!treeCollapsed" class="device-tree">
        <div class="tree-head">
          <span>设备树</span>
          <el-button link size="small" @click="toggleTree">收起</el-button>
        </div>
        <el-tree
          :data="treeNodes"
          node-key="id"
          :props="{ label: 'label', children: 'children' }"
          default-expand-all
          highlight-current
          @node-click="onTreeClick"
        />
        <div class="tree-foot">
          <el-tag v-if="groupFilter.label !== '全部设备'" size="small" closable @close="onTreeClick({ id: -1 })">
            当前：{{ groupFilter.label }}
          </el-tag>
        </div>
      </aside>
      <div class="devices-main">
    <StateBlock v-if="loading" type="loading" title="加载设备数据…" description="正在同步云机状态与分组" />
    <StateBlock
      v-else-if="!filtered.length"
      type="empty"
      title="暂无设备"
      description="还没有云机。点击右上角「创建云机」开始，或先检查分组/筛选条件。"
    >
      <template #action>
        <el-button v-if="auth.can('operator')" type="primary" size="small" @click="createDlg = true">创建云机</el-button>
      </template>
    </StateBlock>
    <el-table v-else-if="viewMode === 'table'" :data="displayed" border stripe style="width: 100%" size="small" @selection-change="(rows) => selectedIds = rows.map(r => r.id)" @row-contextmenu="openCtx">
      <el-table-column type="selection" width="45" />
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="名称" width="140" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag v-if="row.is_banned" type="danger" size="small">已封禁</el-tag>
          <el-tag v-else-if="store.renewProgress[row.id]" :type="renewTagType(store.renewProgress[row.id].phase)" size="small">
            <el-icon
              v-if="!['done', 'failed'].includes(store.renewProgress[row.id].phase)"
              class="is-loading"
              style="vertical-align: -2px; margin-right: 3px"
            ><Loading /></el-icon>
            {{ RENEW_PHASE_TEXT[store.renewProgress[row.id].phase] || store.renewProgress[row.id].phase }}
          </el-tag>
          <el-tag v-else :type="statusType[row.status]" size="small">{{ statusText[row.status] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="机型" width="150">
        <template #default="{ row }">{{ row.fingerprint?.device?.model }}</template>
      </el-table-column>
      <el-table-column v-if="showIp" label="出口 IP" width="130">
        <template #default="{ row }">{{ row.fingerprint?.network?.exit_ip }}</template>
      </el-table-column>
      <el-table-column label="皮肤" width="150">
        <template #default="{ row }">
          <template v-if="store.skinProgress[row.id]">
            <el-tag
              size="small"
              :type="{ done: 'success', failed: 'danger' }[store.skinProgress[row.id].phase] || 'warning'"
            >
              <el-icon
                v-if="!['done', 'failed'].includes(store.skinProgress[row.id].phase)"
                class="is-loading"
                style="vertical-align: -2px; margin-right: 3px"
              ><Loading /></el-icon>
              {{ SKIN_PHASE_TEXT[store.skinProgress[row.id].phase] || store.skinProgress[row.id].phase }}
            </el-tag>
          </template>
          <el-tag v-else size="small" effect="plain" type="warning">{{ skinLabel(row.skin) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="当前页面" min-width="180">
        <template #default="{ row }">
          <span class="text-primary">{{ row.current_url || '主屏（iOS 皮肤）' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="分组" width="130">
        <template #default="{ row }">
          <el-select
            :model-value="row.group_id"
            size="small"
            placeholder="—"
            clearable
            :disabled="!auth.can('operator')"
            @change="(v) => assignGroup(row, v)"
          >
            <el-option v-for="g in store.groups" :key="g.id" :label="g.name" :value="g.id" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="剩余时长" width="150">
        <template #default="{ row }">
          <span :class="{ 'text-danger': row.is_expiring_soon }">{{ remainingText(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="占用" width="140">
        <template #default="{ row }">
          <template v-if="row.claimed_by">
            <el-tag size="small" type="warning" effect="plain">{{ row.claimed_by }}</el-tag>
            <el-button v-if="auth.can('operator')" link size="small" type="primary" @click="releaseRow(row)">释放</el-button>
          </template>
          <el-button v-else-if="auth.can('operator')" link size="small" type="primary" @click="claimRow(row)">占用</el-button>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="880" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="router.push(`/device/${row.id}?from=devices`)">操控</el-button>
          <el-button size="small" @click="openFloat(row)">浮窗</el-button>
          <el-button size="small" @click="router.push(`/detail/${row.id}?from=devices`)">详情</el-button>
          <el-button size="small" @click="showFp(row)">指纹</el-button>
          <el-button v-if="!isPhysical" size="small" @click="openSnaps(row)">快照</el-button>
          <el-dropdown v-if="!isPhysical && auth.can('operator')" size="small" trigger="click" style="margin: 0 8px" @command="(t) => applySkinRow(row.id, t)">
            <el-button size="small" type="warning" plain>
              换肤<el-icon style="margin-left: 2px"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <!-- 当前主题不禁用：允许「重新落地」（新建机默认 ios 但真机未落地时用得上） -->
                <el-dropdown-item
                  v-for="t in skinThemes"
                  :key="t.key"
                  :command="t.key"
                >{{ t.label }}{{ (row.skin || 'ios') === t.key ? ' ✓' : '' }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button v-if="!isPhysical && auth.can('operator')" size="small" plain @click="openReset('restore_snapshot', row)">
            恢复到快照
          </el-button>
          <el-button v-if="!isPhysical && auth.can('operator')" size="small" type="danger" plain @click="openRenew(row)">
            新机
          </el-button>
          <el-button v-if="auth.can('operator')" size="small" type="danger" @click="openReset('wipe', row)">
            清空数据
          </el-button>
          <el-button
            v-if="isPhysical && auth.can('operator')"
            size="small"
            type="success"
            @click="act(api.startDevice, row.id, '已连接')"
            >连接</el-button
          >
          <el-button
            v-else-if="auth.can('operator') && row.status !== 'running'"
            size="small"
            type="success"
            @click="act(api.startDevice, row.id, '已启动')"
            >启动</el-button
          >
          <el-button v-else-if="auth.can('operator')" size="small" type="warning" @click="act(api.stopDevice, row.id, '已停止')"
            >停止</el-button
          >
          <el-button v-if="auth.can('operator')" size="small" type="warning" plain @click="act(api.restartDevice, row.id, '已重启')"
            >重启</el-button
          >
          <el-button size="small" :loading="shootingId === row.id" @click="takeShot(row)">截图</el-button>
          <el-dropdown v-if="auth.can('operator')" trigger="click" @command="(gid) => moveToGroup(row, gid)">
            <el-button size="small" plain>
              分组<el-icon style="margin-left: 2px"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item :command="0">未分组</el-dropdown-item>
                <el-dropdown-item v-for="g in store.groups" :key="g.id" :command="g.id">{{ g.name }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button v-if="auth.can('operator')" size="small" @click="rename(row)">改名</el-button>
          <el-button v-if="auth.can('operator')" size="small" plain @click="setExpiry(row)">到期</el-button>
          <el-button v-if="row.is_banned && auth.can('operator')" size="small" type="success" plain @click="unbanDevice(row)">解封</el-button>
          <el-button v-else-if="auth.can('operator')" size="small" type="warning" plain @click="openBan(row)">封禁</el-button>
          <el-button v-if="auth.can('operator')" size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-else class="card-grid">
      <div v-for="d in displayed" :key="d.id" @contextmenu="openCtx($event, d)">
        <DeviceCard
          :device="d"
          :groups="store.groups"
          :selected="selectedIds.includes(d.id)"
          :can-write="auth.can('operator')"
          :show-ip="showIp"
          @toggle-select="toggleCardSelect"
          @open="(x) => router.push(`/device/${x.id}?from=devices`)"
          @float="openFloat"
          @detail="(x) => router.push(`/detail/${x.id}?from=devices`)"
          @shot="takeShot"
          @restore="(x) => openReset('restore_snapshot', x)"
          @wipe="(x) => openReset('wipe', x)"
          @start="(x) => act(api.startDevice, x.id, '已开机')"
          @stop="(x) => act(api.stopDevice, x.id, '已关机')"
          @restart="(x) => act(api.restartDevice, x.id, '已重启')"
          @claim="claimRow"
          @release="releaseRow"
          @renew="(x) => openRenew([x])"
          @rename="rename"
          @remove="remove"
          @expiry="setExpiry"
        />
      </div>
    </div>
    </div>
    </div>

    <!-- 右键菜单（V1-3） -->
    <div v-if="ctx.visible" class="ctx-menu" :style="{ left: `${ctx.x}px`, top: `${ctx.y}px` }" @click.stop>
      <div class="ctx-item" @click="ctxAction('restart')">重启设备</div>
      <div class="ctx-item" @click="ctxAction('shot')">截图</div>
      <div class="ctx-item" @click="ctxAction('restore')">恢复到快照</div>
      <div class="ctx-item" @click="ctxAction('wipe')">清空数据（保留设备）</div>
      <div class="ctx-item" @click="ctxAction('detail')">设备详情</div>
      <div class="ctx-item" @click="ctxAction('move')">移入分组</div>
      <div class="ctx-item" @click="ctxAction('bind')">绑定 IP</div>
    </div>

    <!-- 移组 -->
    <el-dialog v-model="moveDlg" title="移入分组" width="380px">
      <el-select v-model="moveGroupId" placeholder="选择分组（留空为移出）" style="width: 100%">
        <el-option label="不分组" :value="0" />
        <el-option v-for="g in store.groups" :key="g.id" :label="g.name" :value="g.id" />
      </el-select>
      <template #footer>
        <el-button @click="moveDlg = false">取消</el-button>
        <el-button type="primary" :loading="moving" @click="submitMove">确认</el-button>
      </template>
    </el-dialog>

    <!-- 绑定 IP -->
    <el-dialog v-model="bindDlg" title="绑定 IP 资源" width="480px">
      <div v-loading="bindLoading" style="min-height: 120px">
        <el-alert v-if="bindError" type="error" :closable="false" show-icon :title="bindError" />
        <template v-else>
          <p class="bind-hint">
            目标设备：<b>#{{ bindDevice?.id }} {{ bindDevice?.name }}</b>
            · 当前：{{ bindDevice?.ip_id ? `已绑定 #${bindDevice.ip_id}` : '未绑定' }}
          </p>
          <el-select v-model="bindIpId" filterable placeholder="选择可用 IP" style="width: 100%" no-data-text="暂无可用 IP">
            <el-option
              v-for="ip in bindIps"
              :key="ip.id"
              :label="`#${ip.id} ${ip.ip}:${ip.port}${ip.region ? ' · ' + ip.region : ''}`"
              :value="ip.id"
            />
          </el-select>
          <p class="bind-hint">绑定后会应用到设备网络指纹（下次开机/新机生效）。</p>
        </template>
      </div>
      <template #footer>
        <el-button @click="bindDlg = false">取消</el-button>
        <el-button type="primary" :disabled="!bindIpId || !!bindError" :loading="binding" @click="submitBind">绑定</el-button>
      </template>
    </el-dialog>

    <FloatingPlayer
      v-for="(f, i) in floats"
      :key="f.device.id"
      :device="f.device"
      :visible="true"
      :offset="i"
      :z-index="f.z"
      @update:visible="closeFloat(f.device.id)"
      @open-page="openPageFromFloat"
      @focus="focusFloat(f.device.id)"
    />
    <el-dialog v-model="shotDlg" :title="`截图 · ${shotDevice?.name || ''}`" width="640px">
      <div v-loading="shotLoading" class="shot-wrap">
        <img v-if="shotFrame" :src="shotFrame" alt="设备截图" class="shot-img" />
      </div>
      <template #footer>
        <el-button @click="shotDlg = false">关闭</el-button>
        <el-button type="primary" :disabled="!shotFrame" @click="downloadShot">下载 PNG</el-button>
      </template>
    </el-dialog>

    <!-- 批量建机 -->
    <el-dialog v-model="createDlg" title="批量创建云手机" width="440px">
      <el-form label-width="92px">
        <el-form-item label="数量"><el-input-number v-model="form.count" :min="1" :max="50" /></el-form-item>
        <el-form-item label="名称前缀"><el-input v-model="form.name_prefix" /></el-form-item>
        <el-form-item label="分组">
          <el-select v-model="form.group_id" placeholder="不分组" clearable style="width: 100%">
            <el-option v-for="g in store.groups" :key="g.id" :label="g.name" :value="g.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="分辨率">
          <el-select v-model="form.width" style="width: 110px">
            <el-option :value="720" label="720" />
            <el-option :value="1080" label="1080" />
          </el-select>
          <span style="margin: 0 6px">×</span>
          <el-select v-model="form.height" style="width: 110px">
            <el-option :value="1280" label="1280" />
            <el-option :value="1920" label="1920" />
          </el-select>
        </el-form-item>
        <el-form-item label="首页网址"><el-input v-model="form.target_url" placeholder="留空则显示 iOS 主屏" /></el-form-item>
        <el-form-item label="创建后启动"><el-switch v-model="form.auto_start" /></el-form-item>
        <el-form-item label="指纹策略">
          <el-select v-model="form.fingerprint_mode" placeholder="选择策略" style="width: 100%">
            <el-option
              v-for="p in fingerprintPolicies"
              :key="p.mode"
              :label="`${p.label} (${p.mode})`"
              :value="p.mode"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="区域">
          <el-select v-model="form.region" placeholder="global" clearable style="width: 100%">
            <el-option label="Global" value="global" />
            <el-option label="CN" value="cn" />
            <el-option label="US" value="us" />
            <el-option label="EU" value="eu" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDlg = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="batchCreate">开始创建</el-button>
      </template>
    </el-dialog>

    <!-- 接入实体机 -->
    <el-dialog v-model="adbDlg" title="接入实体机" width="640px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="手机需开启开发者选项与 USB 调试；无线调试请先在服务器执行 adb connect。平台只记录设备原值，不修改 IMEI / 序列号 / Android ID。"
      />
      <div class="snap-toolbar">
        <span class="dialog-hint" style="margin-left: 0; flex: 1">当前后端：{{ backendName }}</span>
        <el-button :icon="'Refresh'" :loading="adbLoading" @click="scanAdb">重新扫描</el-button>
      </div>
      <el-alert
        v-if="adbError"
        type="error"
        :closable="false"
        show-icon
        :title="adbError"
        style="margin-bottom: 12px"
      />
      <el-table v-loading="adbLoading" :data="adbDevices" border size="small" empty-text="未发现 ADB 设备">
        <el-table-column prop="serial" label="序列号" min-width="170" />
        <el-table-column prop="model" label="型号" width="140" />
        <el-table-column prop="state" label="状态" width="100" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              :disabled="row.state !== 'device' || row.adopted"
              :loading="adoptingSerial === row.serial"
              @click="adoptRow(row)"
            >{{ row.adopted ? '已接入' : '接入' }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 一键换肤 -->
    <el-dialog v-model="skinDlg" title="一键换肤" width="460px">
      <el-form label-width="92px">
        <el-form-item label="皮肤主题">
          <el-radio-group v-model="skinForm.theme">
            <el-radio-button v-for="t in skinThemes" :key="t.key" :value="t.key">{{ t.label }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="应用范围">
          <el-radio-group v-model="skinForm.scope">
            <el-radio value="all">全部设备（{{ store.list.length }} 台）</el-radio>
            <el-radio value="filtered">当前筛选结果（{{ filtered.length }} 台）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="换肤两步生效：① 多画面预览/投屏即时切换主题（0 延迟）；② 真机后台逐台落地 —— 装 iOS 启动器(首次)→布置 4 列桌面/Dock→写入壁纸→重启生效，每台约 1–2 分钟，多台顺序进行；实时进度见列表「皮肤」列。"
        />
      </el-form>
      <template #footer>
        <el-button @click="skinDlg = false">取消</el-button>
        <el-button type="primary" :loading="skinning" @click="applySkinBatch">应用换肤</el-button>
      </template>
    </el-dialog>

    <!-- 一键新机（仅虚拟设备；与「清空数据（保留设备）」是两个不同入口） -->
    <el-dialog v-model="renewDlg" title="一键新机" width="480px">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="新机会删除设备内全部应用、账号与文件，并重建实例、更换设备身份；每台约 1–3 分钟（含重启与皮肤落地），期间该设备不可操作。若只想清空数据并保留设备身份，请使用行内「清空数据（保留设备）」。"
      />
      <el-form label-width="96px" style="margin-top: 16px">
        <el-form-item label="目标设备">
          <span>
            {{ renewTargets.length }} 台：{{ renewTargets.slice(0, 5).map((d) => d.name).join('、') }}{{ renewTargets.length > 5 ? ' 等' : '' }}
          </span>
        </el-form-item>
        <el-form-item label="换机模式">
          <div class="renew-mode-hint">
            重新生成 Android ID / 序列号 / IMEI / MAC，等同于一台全新手机。
          </div>
        </el-form-item>
        <el-form-item label="更换出口 IP">
          <el-switch v-model="renewForm.rotate_proxy" />
          <span class="dialog-hint">从代理池换一个新代理；未配置代理池时保持原出口</span>
        </el-form-item>
        <el-form-item label="保留首页">
          <el-switch v-model="renewForm.keep_url" />
          <span class="dialog-hint">开机后自动重新打开当前页面</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="renewDlg = false">取消</el-button>
        <el-button type="danger" :loading="renewing" @click="submitRenew">开始新机</el-button>
      </template>
    </el-dialog>

    <!-- 重置两入口（V3）：恢复到快照 / 清空数据（保留设备），均需输入设备名二次确认 -->
    <el-dialog v-model="resetDlg" :title="resetTitle" width="520px">
      <el-alert
        v-if="resetMode === 'restore_snapshot'"
        type="warning"
        :closable="false"
        show-icon
        title="恢复到快照"
        description="将用该设备最近一次可用快照覆盖当前全部数据并重启。设备记录与绑定关系不变；未创建过任何可用快照时后端会明确报错，不会假成功。此操作不可撤销。"
      />
      <el-alert
        v-else
        type="danger"
        :closable="false"
        show-icon
        title="清空数据（保留设备）"
        description="将真实擦除设备内的应用、账号、文件与运行态并重启。设备记录、分组、断占与 IP 绑定保留，设备身份不变。此操作不依赖快照，且不可撤销；与「恢复到快照」不是同一操作。"
      />
      <el-form label-width="92px" style="margin-top: 16px">
        <el-form-item label="目标设备">
          <span>{{ resetDevice?.name }}</span>
        </el-form-item>
        <el-form-item label="二次确认">
          <el-input
            v-model="resetName"
            :placeholder="`请输入设备名「${resetDevice?.name || ''}」`"
            clearable
            @keyup.enter="submitReset"
          />
          <div class="dialog-hint">必须与设备名完全一致，后端会再次校验，避免误操作清数据。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetDlg = false">取消</el-button>
        <el-button
          type="danger"
          :loading="resetBusy"
          :disabled="resetName.trim() !== (resetDevice?.name || '')"
          @click="submitReset"
        >
          {{ resetSubmitText }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 封禁设备 -->
    <el-dialog v-model="banDlg" title="封禁设备" width="420px">
      <el-form label-width="80px">
        <el-form-item label="设备名"><span>{{ banning?.name }}</span></el-form-item>
        <el-form-item label="封禁原因">
          <el-input v-model="banReason" type="textarea" :rows="3" placeholder="请输入封禁原因" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="banDlg = false">取消</el-button>
        <el-button type="danger" @click="banDevice">确认封禁</el-button>
      </template>
    </el-dialog>

    <!-- 设备快照 -->
    <el-drawer v-model="snapDlg" :title="`设备快照 · ${snapDevice?.name || ''}`" size="560px">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="快照备份设备内的应用、账号、文件与当前页面，不回滚设备身份；创建与恢复期间设备会暂停/重启。"
      />
      <div class="snap-toolbar">
        <el-input
          v-model="snapName"
          placeholder="快照名称（留空自动生成）"
          maxlength="64"
          clearable
          @keyup.enter="createSnap"
        />
        <el-button v-if="auth.can('operator')" type="primary" :loading="snapCreating" @click="createSnap">创建快照</el-button>
      </div>
      <el-table v-loading="snapLoading" :data="snapshots" border size="small" empty-text="暂无快照">
        <el-table-column prop="id" label="ID" width="56" />
        <el-table-column label="名称" min-width="120">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.status === 'error' && row.note"
              :content="row.note"
              placement="top"
            >
              <span>
                <el-icon style="color: #f56c6c; vertical-align: -2px; margin-right: 4px"><WarningFilled /></el-icon>
                {{ row.name }}
              </span>
            </el-tooltip>
            <span v-else>{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="86">
          <template #default="{ row }">{{ fmtSize(row.size_bytes) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="86">
          <template #default="{ row }">
            <el-tag :type="snapStatusType[row.status] || 'info'" size="small">
              {{ snapStatusText[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="warning"
              plain
              :disabled="row.status !== 'ready' || (snapBusyId && snapBusyId !== row.id)"
              :loading="snapBusyId === row.id"
              @click="restoreSnap(row)"
            >
              恢复
            </el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="row.status === 'restoring' || (snapBusyId && snapBusyId !== row.id)"
              @click="deleteSnap(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>

    <!-- 指纹详情 -->
    <el-drawer
      v-model="fpDlg"
      :title="`${fpDevice?.fingerprint?.mode === 'physical' ? '设备信息' : '一机一码'} · ${fpDevice?.name}`"
      size="420px"
    >
      <template v-if="fpDevice">
        <el-descriptions title="设备标识" :column="1" border size="small">
          <el-descriptions-item label="新机/清空次数">{{ fpDevice.renew_count || 0 }} 次</el-descriptions-item>
          <el-descriptions-item label="品牌/机型">{{ fpDevice.fingerprint.device.brand }} · {{ fpDevice.fingerprint.device.model }}</el-descriptions-item>
          <el-descriptions-item v-if="fpDevice.fingerprint.device.serial" label="ADB 序列号">{{ fpDevice.fingerprint.device.serial }}</el-descriptions-item>
          <el-descriptions-item v-if="fpDevice.fingerprint.device.android_version" label="Android">{{ fpDevice.fingerprint.device.android_version }}</el-descriptions-item>
          <el-descriptions-item v-if="fpDevice.fingerprint.device.android_id" label="Android ID">{{ fpDevice.fingerprint.device.android_id }}</el-descriptions-item>
          <el-descriptions-item v-if="fpDevice.fingerprint.device.serialno" label="序列号">{{ fpDevice.fingerprint.device.serialno }}</el-descriptions-item>
          <el-descriptions-item v-if="fpDevice.fingerprint.device.imei" label="IMEI">{{ fpDevice.fingerprint.device.imei }}</el-descriptions-item>
          <el-descriptions-item v-if="fpDevice.fingerprint.device.mac" label="MAC">{{ fpDevice.fingerprint.device.mac }}</el-descriptions-item>
        </el-descriptions>
        <el-descriptions v-if="fpDevice.fingerprint.browser?.user_agent" title="浏览器指纹" :column="1" border size="small" style="margin-top: 14px">
          <el-descriptions-item label="UA">{{ fpDevice.fingerprint.browser.user_agent }}</el-descriptions-item>
          <el-descriptions-item label="时区/语言">{{ fpDevice.fingerprint.browser.timezone }} / {{ fpDevice.fingerprint.browser.language }}</el-descriptions-item>
          <el-descriptions-item label="WebGL">{{ fpDevice.fingerprint.browser.webgl_renderer }}</el-descriptions-item>
          <el-descriptions-item label="Canvas 噪声">{{ fpDevice.fingerprint.browser.canvas_noise_seed }}</el-descriptions-item>
        </el-descriptions>
        <el-descriptions title="网络" :column="1" border size="small" style="margin-top: 14px">
          <template v-if="fpDevice.fingerprint.mode === 'physical'">
            <el-descriptions-item label="出口 IP">设备原网络（平台未接管）</el-descriptions-item>
          </template>
          <template v-else>
            <el-descriptions-item label="出口 IP">{{ fpDevice.fingerprint.network.exit_ip }}</el-descriptions-item>
            <el-descriptions-item label="代理">{{ fpDevice.fingerprint.network.proxy || '直连' }}</el-descriptions-item>
          </template>
        </el-descriptions>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.loading-placeholder {
  padding: 60px 0;
  text-align: center;
  color: var(--color-text-muted);
}
.loading-placeholder p {
  margin-top: 12px;
}
.dialog-hint {
  margin-left: 10px;
  color: var(--color-text-muted);
  font-size: 12px;
}
.renew-mode-hint {
  margin-top: 4px;
  color: var(--color-text-muted);
  font-size: 12px;
  line-height: 1.5;
}
.snap-toolbar {
  display: flex;
  gap: 10px;
  margin: 14px 0;
}
.snap-toolbar .el-input {
  flex: 1;
}
.shot-wrap {
  min-height: 120px;
  display: flex;
  justify-content: center;
}
.shot-img {
  max-width: 100%;
  max-height: 520px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.expire-alert {
  margin-bottom: 12px;
}
.expire-sub {
  color: var(--color-text-muted);
  font-size: 12px;
}
.text-danger {
  color: var(--color-danger);
  font-weight: 600;
}

/* V1-3 设备树 / 右键菜单（新组件统一走 tokens） */
.devices-body {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
}
.devices-main {
  flex: 1;
  min-width: 0;
}
.device-tree {
  flex: none;
  width: 220px;
  max-height: calc(100vh - 170px);
  overflow: auto;
  padding: var(--sp-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-elevated);
  position: sticky;
  top: var(--sp-3);
}
.tree-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--sp-1) var(--sp-2);
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}
.tree-foot {
  margin-top: var(--sp-2);
}
.ctx-menu {
  position: fixed;
  z-index: var(--z-dropdown);
  min-width: 140px;
  padding: var(--sp-1);
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
}
.ctx-item {
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--radius-sm);
  font-size: var(--font-sm);
  color: var(--color-text-primary);
  cursor: pointer;
}
.ctx-item:hover {
  background: var(--color-bg-hover);
}
.bind-hint {
  margin: var(--sp-2) 0;
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}
</style>
