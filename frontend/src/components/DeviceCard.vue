<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useThumbnail } from '../composables/useThumbnail'

const props = defineProps({
  device: { type: Object, required: true },
  groups: { type: Array, default: () => [] },
  selected: { type: Boolean, default: false },
  canWrite: { type: Boolean, default: false },
  showIp: { type: Boolean, default: true },
})
const emit = defineEmits([
  'toggle-select', 'open', 'detail', 'float', 'shot', 'start', 'stop', 'restart',
  'renew', 'rename', 'remove', 'claim', 'release', 'expiry', 'restore', 'wipe',
])

const thumbRef = ref(null)
const { frame } = useThumbnail(props.device.id, 30000, thumbRef)

const statusType = { running: 'success', stopped: 'info', creating: 'warning', error: 'danger' }
const statusText = { running: '运行中', stopped: '已停止', creating: '创建中', error: '异常' }
const ip = computed(() => props.device.fingerprint?.network?.exit_ip || '')
const groupName = computed(
  () => props.groups.find((g) => g.id === props.device.group_id)?.name || '未分组',
)
const online = computed(() => props.device.status === 'running')

const remainingText = computed(() => {
  if (typeof props.device.remaining_seconds === 'number') return fmtRemaining(props.device.remaining_seconds)
  if (props.device.expires_at) {
    const ms = new Date(props.device.expires_at).getTime() - Date.now()
    return fmtRemaining(Math.max(0, Math.floor(ms / 1000)))
  }
  return '未设置到期'
})
const expiringSoon = computed(() => {
  if (typeof props.device.remaining_seconds === 'number') return props.device.remaining_seconds <= 86400
  if (props.device.expires_at) {
    return new Date(props.device.expires_at).getTime() - Date.now() <= 86400000
  }
  return false
})

function fmtRemaining(sec) {
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  return d > 0 ? `剩余 ${d} 天 ${h} 小时` : `剩余 ${h} 小时`
}

async function copy(text) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(`已复制：${text}`)
  } catch {
    ElMessage.warning('浏览器不支持剪贴板，请手动复制')
  }
}

function onCommand(cmd) {
  emit(cmd, props.device)
}
</script>

<template>
  <div class="device-card" :class="{ selected, expiring: expiringSoon }">
    <div v-if="expiringSoon" class="expiry-bar">
      <el-icon><AlarmClock /></el-icon>
      <span>{{ remainingText }}，即将到期</span>
    </div>

    <div class="card-head">
      <el-checkbox :model-value="selected" @change="emit('toggle-select', device)" />
      <span class="status-dot" :class="{ on: online }"></span>
      <span class="name" :title="device.name">{{ device.name }}</span>
      <el-tag :type="statusType[device.status]" size="small" effect="plain" round>
        {{ statusText[device.status] }}
      </el-tag>
      <el-dropdown trigger="click" @command="onCommand">
        <button class="more-btn" type="button" title="更多操作"><el-icon><MoreFilled /></el-icon></button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="detail">设备详情</el-dropdown-item>
            <el-dropdown-item command="shot">高清截图</el-dropdown-item>
            <el-dropdown-item v-if="canWrite" command="restart">重启</el-dropdown-item>
            <el-dropdown-item v-if="canWrite" command="restore">恢复到快照</el-dropdown-item>
            <el-dropdown-item v-if="canWrite" command="wipe" divided>清空数据</el-dropdown-item>
            <el-dropdown-item v-if="canWrite" command="renew">一键新机</el-dropdown-item>
            <el-dropdown-item v-if="canWrite" command="expiry">设置到期</el-dropdown-item>
            <el-dropdown-item v-if="canWrite" command="rename">改名</el-dropdown-item>
            <el-dropdown-item v-if="canWrite" command="claim">占用</el-dropdown-item>
            <el-dropdown-item v-if="canWrite" command="release">释放</el-dropdown-item>
            <el-dropdown-item v-if="canWrite" command="remove" divided>删除</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <div ref="thumbRef" class="thumb" @click="emit('open', device)">
      <img v-if="frame" :src="frame" alt="缩略图" draggable="false" />
      <div v-else class="thumb-empty">
        <el-icon class="is-loading"><Loading /></el-icon>
      </div>
      <span class="group-tag">{{ groupName }}</span>
      <span v-if="online" class="live-tag"><i></i>LIVE</span>
    </div>

    <div class="meta">
      <div class="row">
        <span class="label">云机号</span>
        <span class="value mono">#{{ device.id }}</span>
        <button class="copy-btn" type="button" @click="copy(String(device.id))">复制</button>
      </div>
      <div v-if="showIp" class="row">
        <span class="label">IP</span>
        <span class="value mono">{{ ip || '未分配' }}</span>
      </div>
      <div class="row">
        <span class="label">时长</span>
        <span class="value" :class="{ 'text-danger': expiringSoon }">{{ remainingText }}</span>
      </div>
      <div class="row">
        <span class="label">机型</span>
        <span class="value">{{ device.fingerprint?.device?.model || '—' }}</span>
      </div>
    </div>

    <div class="card-actions">
      <el-button class="primary-action" size="small" type="primary" @click="emit('open', device)">操控</el-button>
      <el-button size="small" @click="emit('float', device)">浮窗</el-button>
      <el-button v-if="canWrite" size="small" :type="device.status === 'running' ? 'warning' : 'success'" plain @click="emit(device.status === 'running' ? 'stop' : 'start', device)">
        {{ device.status === 'running' ? '关机' : '开机' }}
      </el-button>
      <el-button size="small" text @click="emit('detail', device)">详情</el-button>
    </div>
  </div>
</template>

<style scoped>
.device-card {
  position: relative;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--sp-2);
  background: var(--color-bg-surface);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  transition: border-color var(--ease-fast), box-shadow var(--ease-fast), transform var(--ease-fast);
  overflow: hidden;
}
.device-card:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}
.device-card.selected {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--color-primary-weak);
}
.device-card.expiring {
  border-color: color-mix(in srgb, var(--color-danger) 55%, var(--color-border));
}
.expiry-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: calc(var(--sp-2) * -1) calc(var(--sp-2) * -1) 0;
  padding: 4px 10px;
  background: var(--color-danger-weak);
  color: var(--color-danger);
  font-size: 11px;
  font-weight: 600;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.card-head .name {
  font-weight: 600;
  font-size: var(--font-sm);
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-text-muted);
  flex: none;
}
.status-dot.on {
  background: var(--color-success);
  box-shadow: 0 0 8px color-mix(in srgb, var(--color-success) 60%, transparent);
}
.more-btn {
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  width: 24px;
  height: 24px;
  border-radius: var(--radius-sm);
  display: inline-grid;
  place-items: center;
  cursor: pointer;
}
.more-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}
.thumb {
  position: relative;
  aspect-ratio: 9 / 16;
  max-height: 210px;
  background: var(--color-bg-sunken);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.thumb-empty {
  color: var(--color-text-muted);
}
.group-tag {
  position: absolute;
  left: 6px;
  bottom: 6px;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
}
.live-tag {
  position: absolute;
  right: 6px;
  top: 6px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  letter-spacing: 0.08em;
  font-weight: 700;
  color: #fff;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  background: rgba(0, 0, 0, 0.55);
}
.live-tag i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-success);
  box-shadow: 0 0 6px var(--color-success);
}
.meta {
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.meta .row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.meta .label {
  width: 44px;
  color: var(--color-text-muted);
  flex: none;
}
.meta .value {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.copy-btn {
  border: none;
  background: transparent;
  color: var(--color-primary);
  font-size: 11px;
  cursor: pointer;
  padding: 0;
}
.mono {
  font-family: Consolas, 'SFMono-Regular', monospace;
}
.text-danger {
  color: var(--color-danger);
  font-weight: 600;
}
.card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.card-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
.primary-action {
  flex: 1;
  min-width: 64px;
}
</style>
