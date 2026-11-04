<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDevices } from '../stores/devices'

const router = useRouter()
const route = useRoute()
const store = useDevices()

const STORAGE_KEY = 'workbench.tabs.v1'
const MAX_TABS = 8

// 标签：{ path, title, pinned }。多设备操控时按设备名区分，同一路径不重复开。
const tabs = ref([])
const scrollRef = ref(null)

function titleFor(path, meta) {
  const m = path.match(/^\/device\/(\d+)/)
  if (m) {
    const d = store.list.find((x) => x.id === Number(m[1]))
    return d ? `操控 · #${d.id} ${d.name}` : `操控 · #${m[1]}`
  }
  const dm = path.match(/^\/detail\/(\d+)/)
  if (dm) {
    const d = store.list.find((x) => x.id === Number(dm[1]))
    return d ? `详情 · #${d.id} ${d.name}` : `详情 · #${dm[1]}`
  }
  return meta?.title || path
}

function persist() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(tabs.value))
}

function addTab(path, meta) {
  if (path === '/login' || !path.startsWith('/') || path === '/') return
  const exists = tabs.value.find((t) => t.path === path)
  if (exists) {
    exists.title = titleFor(path, meta)
    persist()
    return
  }
  if (tabs.value.length >= MAX_TABS) {
    // 固定标签不参与淘汰：只挤掉最旧的未固定标签
    const idx = tabs.value.findIndex((t) => !t.pinned)
    if (idx >= 0) tabs.value.splice(idx, 1)
  }
  tabs.value.push({ path, title: titleFor(path, meta), pinned: false })
  persist()
  scrollActiveIntoView()
}

function goFallback() {
  const target = tabs.value.find((t) => t.pinned) || tabs.value[0]
  router.push(target ? target.path : '/devices')
}

function closeTab(tab, event) {
  event?.stopPropagation()
  const idx = tabs.value.findIndex((t) => t.path === tab.path)
  if (idx < 0) return
  const wasActive = route.path === tab.path
  tabs.value.splice(idx, 1)
  persist()
  if (wasActive) {
    const next = tabs.value[Math.min(idx, tabs.value.length - 1)]
    router.push(next ? next.path : '/devices')
  }
}

function closeOthers(tab) {
  tabs.value = tabs.value.filter((t) => t === tab || t.pinned)
  persist()
  if (!tabs.value.some((t) => t.path === route.path)) router.push(tab.path)
}

function closeRight(tab) {
  const idx = tabs.value.findIndex((t) => t.path === tab.path)
  if (idx < 0) return
  const activeRemoved = tabs.value.findIndex((t, i) => i > idx && t.path === route.path) >= 0
  tabs.value = tabs.value.filter((t, i) => i <= idx || t.pinned)
  persist()
  if (activeRemoved) router.push(tab.path)
}

function togglePin(tab) {
  tab.pinned = !tab.pinned
  persist()
}

function switchTab(tab) {
  if (route.path !== tab.path) router.push(tab.path)
}

function scrollActiveIntoView() {
  nextTick(() => {
    const el = scrollRef.value?.querySelector('.tab.active')
    if (el) el.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  })
}

// 溢出时把竖向滚轮转成横向滚动，避免标签被挤出可视区后无法到达
function onWheel(e) {
  const box = scrollRef.value
  if (!box || box.scrollWidth <= box.clientWidth) return
  if (!e.deltaY) return
  e.preventDefault()
  box.scrollLeft += e.deltaY
}

// ---- 右键菜单 ----
const menu = ref({ open: false, x: 0, y: 0, tab: null })
const menuStyle = computed(() => ({
  left: `${Math.min(menu.value.x, window.innerWidth - 170)}px`,
  top: `${Math.min(menu.value.y, window.innerHeight - 190)}px`,
}))
const hasTabsRight = computed(() => {
  const idx = tabs.value.findIndex((t) => t.path === menu.value.tab?.path)
  return idx >= 0 && idx < tabs.value.length - 1
})

function openMenu(e, tab) {
  if (e.button !== 2) return
  e.preventDefault()
  menu.value = { open: true, x: e.clientX, y: e.clientY, tab }
}

function closeMenu() {
  menu.value = { ...menu.value, open: false, tab: null }
}

function runMenu(cmd) {
  const tab = menu.value.tab
  if (!tab) return
  if (cmd === 'pin') togglePin(tab)
  else if (cmd === 'closeOthers') closeOthers(tab)
  else if (cmd === 'closeRight') closeRight(tab)
  else if (cmd === 'close') closeTab(tab)
  closeMenu()
}

// ---- 拖拽排序 ----
const dragIndex = ref(-1)
function onDragStart(e, index) {
  dragIndex.value = index
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', String(index))
}
function onDragOver(e) {
  if (dragIndex.value < 0) return
  e.preventDefault()
  e.dataTransfer.dropEffect = 'move'
}
function onDrop(e, index) {
  e.preventDefault()
  const from = dragIndex.value
  dragIndex.value = -1
  if (from < 0 || from === index) return
  const [moved] = tabs.value.splice(from, 1)
  tabs.value.splice(index, 0, moved)
  persist()
}
function onDragEnd() {
  dragIndex.value = -1
}

onMounted(() => {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    tabs.value = Array.isArray(raw)
      ? raw
          .filter((t) => t && typeof t.path === 'string' && t.path.startsWith('/'))
          .map((t) => ({ path: t.path, title: t.title || t.path, pinned: !!t.pinned }))
      : []
  } catch {
    tabs.value = []
  }
  // 刷新后恢复上次标签，并把当前路由补进来
  if (route.name && route.name !== 'login') addTab(route.path, route.meta)
  scrollActiveIntoView()
})

onUnmounted(() => closeMenu())

watch(
  () => route.fullPath,
  () => {
    addTab(route.path, route.meta)
    scrollActiveIntoView()
  },
)

// 设备改名/删除后同步标签标题
watch(
  () => store.list,
  () => {
    tabs.value.forEach((t) => {
      if (t.path.startsWith('/device/') || t.path.startsWith('/detail/')) {
        t.title = titleFor(t.path)
      }
    })
  },
  { deep: false },
)
</script>

<template>
  <div class="workbench-tabs">
    <div ref="scrollRef" class="tabs-scroll" @wheel="onWheel">
      <div
        v-for="(t, i) in tabs"
        :key="t.path"
        class="tab"
        :class="{ active: route.path === t.path, pinned: t.pinned, dragging: dragIndex === i }"
        :title="t.title"
        draggable="true"
        @click="switchTab(t)"
        @contextmenu="openMenu($event, t)"
        @dragstart="onDragStart($event, i)"
        @dragover="onDragOver"
        @drop="onDrop($event, i)"
        @dragend="onDragEnd"
      >
        <el-icon v-if="t.pinned" class="pin-icon"><Paperclip /></el-icon>
        <span class="tab-title">{{ t.title }}</span>
        <span class="close" @click="closeTab(t, $event)">×</span>
      </div>
      <span v-if="!tabs.length" class="tabs-empty">
        <el-icon><Guide /></el-icon>
        工作台还没有打开的页面：从左侧菜单进入任意功能，标签会自动收在这里；右键标签可固定、关闭其它或关闭右侧。
      </span>
    </div>

    <teleport to="body">
      <div v-if="menu.open" class="ctx-mask" @click="closeMenu" @contextmenu.prevent="closeMenu"></div>
      <ul v-if="menu.open" class="ctx-menu" :style="menuStyle">
        <li @click="runMenu('pin')">
          <el-icon><Paperclip /></el-icon>{{ menu.tab?.pinned ? '取消固定' : '固定标签' }}
        </li>
        <li @click="runMenu('close')">
          <el-icon><Close /></el-icon>关闭当前
        </li>
        <li @click="runMenu('closeOthers')">
          <el-icon><CircleClose /></el-icon>关闭其它
        </li>
        <li :class="{ disabled: !hasTabsRight }" @click="hasTabsRight && runMenu('closeRight')">
          <el-icon><DArrowRight /></el-icon>关闭右侧
        </li>
      </ul>
    </teleport>
  </div>
</template>

<style scoped>
.workbench-tabs {
  display: flex;
  align-items: center;
  padding: 6px 14px;
  background: var(--color-tabbar-bg);
  border-bottom: 1px solid var(--color-glass-border);
  backdrop-filter: blur(12px);
  flex: none;
}
.tabs-scroll {
  display: flex;
  align-items: center;
  gap: 6px;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
  width: 100%;
  padding-bottom: 2px;
}
.tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 8px;
  font-size: 12px;
  color: var(--color-text-secondary);
  background: var(--color-bg-hover);
  border: 1px solid transparent;
  cursor: pointer;
  white-space: nowrap;
  max-width: 220px;
  flex: none;
  user-select: none;
}
.tab:hover {
  border-color: var(--color-border);
  color: var(--color-text-primary);
}
.tab.active {
  color: #fff;
  background: var(--color-accent-gradient);
  border-color: transparent;
}
.tab.pinned {
  border-color: var(--color-border);
}
.tab.dragging {
  opacity: 0.45;
}
.pin-icon {
  font-size: 12px;
  opacity: 0.85;
}
.tab-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.close {
  opacity: 0.6;
  font-size: 14px;
  line-height: 1;
}
.close:hover {
  opacity: 1;
}
.tabs-empty {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-muted);
  padding: 2px 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ctx-mask {
  position: fixed;
  inset: 0;
  z-index: var(--z-dropdown);
}
.ctx-menu {
  position: fixed;
  z-index: calc(var(--z-dropdown) + 1);
  min-width: 160px;
  margin: 0;
  padding: 4px;
  list-style: none;
  border-radius: var(--radius-md);
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-md);
  font-size: 13px;
  color: var(--color-text-primary);
}
.ctx-menu li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.ctx-menu li:hover {
  background: var(--color-bg-hover);
}
.ctx-menu li.disabled {
  color: var(--color-text-muted);
  cursor: not-allowed;
}
.ctx-menu li.disabled:hover {
  background: transparent;
}
</style>
