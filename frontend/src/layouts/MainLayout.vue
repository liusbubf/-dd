<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'
import { useDevices } from '../stores/devices'
import { useTheme } from '../composables/theme'
import WorkbenchTabs from './WorkbenchTabs.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuth()
const devices = useDevices()
const { mode, setMode } = useTheme()

const THEME_OPTIONS = [
  { key: 'light', label: '浅色', icon: 'Sunny' },
  { key: 'dark', label: '深色', icon: 'Moon' },
  { key: 'system', label: '跟随系统', icon: 'Monitor' },
]
const currentTheme = computed(() => THEME_OPTIONS.find((o) => o.key === mode.value) || THEME_OPTIONS[1])

// 导航分组（可折叠）；路由变化时自动展开所在组，折叠态写 localStorage
const NAV_GROUPS = [
  {
    key: 'overview',
    title: '总览',
    items: [{ path: '/dashboard', label: '数据看板', icon: 'Odometer' }],
  },
  {
    key: 'devices',
    title: '设备管理',
    items: [
      { path: '/devices', label: '我的云机', icon: 'Iphone' },
      { path: '/groups', label: '云机分组', icon: 'FolderOpened' },
      { path: '/grid', label: '多控工作台', icon: 'Grid' },
      { path: '/batch', label: '批量操控', icon: 'Operation' },
    ],
  },
  {
    key: 'network',
    title: '网络',
    items: [{ path: '/ips', label: 'VPC / IP 资源池', icon: 'Connection' }],
  },
  {
    key: 'resource',
    title: '资源',
    items: [
      { path: '/cloud-disk', label: '云盘', icon: 'Files' },
      { path: '/app-library', label: '应用库', icon: 'Collection' },
      { path: '/downloads', label: '下载中心', icon: 'Download' },
      { path: '/files', label: '文件互传', icon: 'Upload' },
      { path: '/apps', label: '应用管理', icon: 'Box' },
    ],
  },
  {
    key: 'ops',
    title: '运营',
    items: [
      { path: '/scripts', label: '脚本回放', icon: 'VideoPlay' },
      { path: '/tasks', label: '任务调度', icon: 'Timer' },
      { path: '/alerts', label: '告警监控', icon: 'Warning' },
      { path: '/reports', label: '统计报表', icon: 'Histogram' },
      { path: '/push-jobs', label: '推送进度', icon: 'Finished' },
      { path: '/logs', label: '设备日志', icon: 'Tickets' },
    ],
  },
  {
    key: 'system',
    title: '系统',
    items: [
      { path: '/users', label: '用户管理', icon: 'User', minRole: 'admin' },
      { path: '/audit', label: '操作审计', icon: 'Document', minRole: 'admin' },
    ],
  },
]

const COLLAPSE_KEY = 'nav.collapsedGroups'
function loadCollapsed() {
  try {
    const arr = JSON.parse(localStorage.getItem(COLLAPSE_KEY) || '[]')
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}
const collapsedGroups = reactive(new Set(loadCollapsed()))
function toggleGroup(key) {
  if (collapsedGroups.has(key)) collapsedGroups.delete(key)
  else collapsedGroups.add(key)
  localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...collapsedGroups]))
}

function resolveMenu(path) {
  if (path.startsWith('/detail/') || path.startsWith('/device/')) {
    const from = route.query.from
    if (from === 'grid') return '/grid'
    if (from === 'devices') return '/devices'
  }
  return path
}
const activeMenu = ref(resolveMenu(route.path))
watch(
  () => route.fullPath,
  () => {
    activeMenu.value = resolveMenu(route.path)
  },
)
watch(
  activeMenu,
  (path) => {
    const g = NAV_GROUPS.find((grp) => grp.items.some((it) => it.path === path))
    if (g && collapsedGroups.has(g.key)) {
      collapsedGroups.delete(g.key)
      localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...collapsedGroups]))
    }
  },
  { immediate: true },
)

function groupItems(group) {
  return group.items.filter((it) => !it.minRole || auth.can(it.minRole))
}

function handleMenuSelect(index) {
  activeMenu.value = index
  requestAnimationFrame(() => router.push(index))
}

// 悬停预加载目标路由 chunk，降低首次点击延迟（每个只预加载一次）
const _prefetched = {}
const _routeComponents = {
  '/dashboard': () => import('../views/Dashboard.vue'),
  '/devices': () => import('../views/Devices.vue'),
  '/groups': () => import('../views/Groups.vue'),
  '/grid': () => import('../views/Grid.vue'),
  '/batch': () => import('../views/Batch.vue'),
  '/apps': () => import('../views/AppManager.vue'),
  '/app-library': () => import('../views/AppLibrary.vue'),
  '/push-jobs': () => import('../views/PushProgress.vue'),
  '/scripts': () => import('../views/Scripts.vue'),
  '/tasks': () => import('../views/Tasks.vue'),
  '/alerts': () => import('../views/Alerts.vue'),
  '/reports': () => import('../views/Reports.vue'),
  '/downloads': () => import('../views/DownloadCenter.vue'),
  '/logs': () => import('../views/Logs.vue'),
  '/files': () => import('../views/FileManager.vue'),
  '/cloud-disk': () => import('../views/CloudDisk.vue'),
  '/ips': () => import('../views/IpPool.vue'),
  '/users': () => import('../views/Users.vue'),
  '/audit': () => import('../views/Audit.vue'),
}
function prefetchRoute(path) {
  if (_prefetched[path]) return
  _prefetched[path] = true
  const loader = _routeComponents[path]
  if (loader) loader().catch(() => {})
}

// 顶栏资源区：只展示后端真实返回值；没有对应能力时显示「未启用」
const expiringCount = ref(null)
const resources = computed(() => [
  { key: 'credits', label: '积分', value: '未启用', icon: 'Coin' },
  { key: 'balance', label: '余额', value: '未启用', icon: 'Wallet' },
  {
    key: 'expiring',
    label: '到期提醒',
    value: expiringCount.value === null ? '未启用' : `${expiringCount.value} 台`,
    icon: 'AlarmClock',
    alert: (expiringCount.value || 0) > 0,
  },
])

onMounted(() => {
  devices.initSocket()
  if (!devices.list.length) devices.refresh().catch(() => {})
  if (!auth.user) auth.fetchMe().catch(() => {})
  api
    .listExpiring(24)
    .then(({ data }) => {
      expiringCount.value = Array.isArray(data) ? data.length : 0
    })
    .catch(() => {
      expiringCount.value = null
    })
})

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="app-brand">
        <span class="app-logo" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="22" height="22">
            <rect x="4" y="3" width="24" height="26" rx="5" fill="none" stroke="currentColor" stroke-width="2" />
            <rect x="8" y="7" width="16" height="14" rx="2" fill="currentColor" opacity="0.28" />
            <circle cx="16" cy="25" r="1.6" fill="currentColor" />
          </svg>
        </span>
        <span class="brand-text">
          <span class="brand-name">顺天云手机</span>
          <span class="brand-sub">Cloud Phone Console</span>
        </span>
      </div>

      <div class="header-title">
        <span class="title-dot"></span>
        <span>{{ route.meta.title || '控制台' }}</span>
      </div>

      <div class="header-spacer"></div>

      <div class="resource-bar">
        <div
          v-for="r in resources"
          :key="r.key"
          class="res-chip"
          :class="{ 'is-alert': r.alert, 'is-off': r.value === '未启用' }"
          :title="r.value === '未启用' ? '后端未提供该数据' : `${r.label}：${r.value}`"
        >
          <el-icon><component :is="r.icon" /></el-icon>
          <span class="res-label">{{ r.label }}</span>
          <span class="res-value">{{ r.value }}</span>
        </div>
      </div>

      <el-tag type="success" effect="plain" class="online-tag">
        在线 {{ devices.running.length }} / {{ devices.list.length }}
      </el-tag>

      <el-tooltip :content="`主题：${currentTheme.label}`" placement="bottom">
        <el-dropdown trigger="click" @command="setMode">
          <span class="icon-btn">
            <el-icon>
              <Sunny v-if="mode === 'light'" />
              <Moon v-else-if="mode === 'dark'" />
              <Monitor v-else />
            </el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="o in THEME_OPTIONS" :key="o.key" :command="o.key">
                <el-icon><component :is="o.icon" /></el-icon>{{ o.label }}
                <el-icon v-if="mode === o.key" style="margin-left: 6px; color: var(--color-primary)"><Check /></el-icon>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-tooltip>

      <el-dropdown @command="logout">
        <span class="user-chip">
          <span class="avatar">{{ (auth.user?.username || '?').slice(0, 1).toUpperCase() }}</span>
          <span class="user-meta">
            <span class="user-name">{{ auth.user?.username || '未登录' }}</span>
            <span class="user-role">
              {{ { superadmin: '超级管理员', admin: '管理员', operator: '操作员', viewer: '查看员' }[auth.role] || auth.role }}
            </span>
          </span>
          <el-icon><ArrowDown /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu><el-dropdown-item @click="logout">退出登录</el-dropdown-item></el-dropdown-menu>
        </template>
      </el-dropdown>
    </header>

    <div class="app-body">
      <aside class="app-aside">
        <nav class="nav-groups">
          <section v-for="g in NAV_GROUPS" :key="g.key" class="nav-group">
            <button class="nav-group-head" type="button" @click="toggleGroup(g.key)">
              <span class="nav-group-title">{{ g.title }}</span>
              <span class="nav-group-count">{{ groupItems(g).length }}</span>
              <el-icon class="chevron" :class="{ collapsed: collapsedGroups.has(g.key) }"><ArrowDown /></el-icon>
            </button>
            <div v-show="!collapsedGroups.has(g.key)" class="nav-items">
              <button
                v-for="it in groupItems(g)"
                :key="it.path"
                type="button"
                class="nav-item"
                :class="{ active: activeMenu === it.path }"
                @mouseenter="prefetchRoute(it.path)"
                @click="handleMenuSelect(it.path)"
              >
                <el-icon class="nav-icon"><component :is="it.icon" /></el-icon>
                <span class="nav-label">{{ it.label }}</span>
              </button>
            </div>
          </section>
        </nav>
      </aside>

      <div class="app-main-col">
        <div class="compliance-banner">
          <el-icon><Warning /></el-icon>
          <span>本平台仅用于软件兼容性测试、自动化测试、授权的红蓝对抗、开发者研究等合法用途。禁止用于绕过检测、破解、欺诈等非法活动，违者将封禁账号和云机。</span>
        </div>
        <WorkbenchTabs />
        <main class="app-main">
          <router-view v-slot="{ Component }">
            <keep-alive include="Devices,Grid">
              <component :is="Component" />
            </keep-alive>
          </router-view>
        </main>
      </div>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-page-gradient);
}
.app-header {
  flex: none;
  height: 60px;
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 0 var(--sp-4);
  background: var(--color-header-bg);
  backdrop-filter: blur(18px);
  border-bottom: 1px solid var(--color-glass-border);
  position: relative;
  z-index: var(--z-sticky);
}
.app-brand {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 204px;
}
.app-logo {
  display: inline-flex;
  width: 34px;
  height: 34px;
  border-radius: var(--radius-lg);
  align-items: center;
  justify-content: center;
  color: #fff;
  background: var(--color-accent-gradient);
  box-shadow: 0 8px 18px rgba(61, 123, 255, 0.35);
}
.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
}
.brand-name {
  font-size: var(--font-lg);
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--color-text-primary);
}
.brand-sub {
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}
.header-title {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding-left: var(--sp-3);
  margin-left: var(--sp-2);
  border-left: 1px solid var(--color-border);
  font-size: var(--font-md);
  font-weight: 600;
  color: var(--color-text-secondary);
}
.title-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-success);
  box-shadow: 0 0 10px color-mix(in srgb, var(--color-success) 60%, transparent);
}
.header-spacer {
  flex: 1;
}
.resource-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.res-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 10px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--color-border);
  background: var(--color-bg-surface);
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}
.res-chip .res-label {
  color: var(--color-text-muted);
}
.res-chip .res-value {
  font-weight: 600;
  color: var(--color-text-primary);
}
.res-chip.is-off .res-value {
  color: var(--color-text-muted);
  font-weight: 500;
}
.res-chip.is-alert {
  border-color: color-mix(in srgb, var(--color-warning) 45%, transparent);
  background: var(--color-warning-weak);
}
.res-chip.is-alert .res-value {
  color: var(--color-warning);
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  background: transparent;
  border: 1px solid var(--color-border);
  cursor: pointer;
  transition: background var(--ease-fast), color var(--ease-fast);
}
.icon-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}
.online-tag {
  border-radius: var(--radius-pill);
  background: var(--color-success-weak);
  border-color: color-mix(in srgb, var(--color-success) 30%, transparent);
  color: var(--color-success);
}
.user-chip {
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 4px 10px 4px 4px;
  border-radius: var(--radius-pill);
  background: var(--color-brand-weak);
  border: 1px solid var(--color-border);
  color: var(--color-text-primary);
}
.avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: inline-grid;
  place-items: center;
  font-weight: 700;
  font-size: var(--font-xs);
  color: #fff;
  background: var(--color-accent-gradient);
}
.user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
}
.user-name {
  font-size: var(--font-xs);
  font-weight: 600;
}
.user-role {
  font-size: 10px;
  color: var(--color-text-muted);
}
.app-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.app-aside {
  flex: none;
  width: 216px;
  background: var(--color-sidebar-bg);
  border-right: 1px solid var(--color-sidebar-active-border);
  overflow-y: auto;
  padding: var(--sp-3) var(--sp-2) var(--sp-4);
}
.nav-groups {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nav-group-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 8px 10px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--color-text-muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  border-radius: var(--radius-md);
}
.nav-group-head:hover {
  background: var(--color-sidebar-hover);
}
.nav-group-title {
  flex: 1;
  text-align: left;
}
.nav-group-count {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, 0.06);
  color: var(--color-text-muted);
}
.chevron {
  transition: transform var(--ease-base);
  font-size: 12px;
}
.chevron.collapsed {
  transform: rotate(-90deg);
}
.nav-items {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px 0 6px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  height: 38px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-sidebar-text);
  font-size: var(--font-sm);
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: background var(--ease-fast), color var(--ease-fast);
}
.nav-item:hover {
  background: var(--color-sidebar-hover);
  color: var(--color-sidebar-active-text);
}
.nav-item.active {
  background: var(--color-sidebar-active-bg);
  border-color: var(--color-sidebar-active-border);
  color: var(--color-sidebar-active-text);
  box-shadow: inset 2px 0 0 var(--color-sidebar-dot);
}
.nav-icon {
  font-size: 16px;
  color: inherit;
}
.app-main-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.compliance-banner {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 6px var(--sp-3);
  background: var(--color-warning-weak);
  border-bottom: 1px solid color-mix(in srgb, var(--color-warning) 25%, transparent);
  font-size: var(--font-xs);
  color: var(--color-warning);
}
.compliance-banner span {
  flex: 1;
  line-height: 1.5;
}
.app-main {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
</style>
