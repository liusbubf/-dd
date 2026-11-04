<script setup>
defineProps({
  type: { type: String, default: 'empty' }, // empty | loading | error
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  compact: { type: Boolean, default: false },
})
</script>

<template>
  <div class="state-block" :class="[`is-${type}`, { compact }]">
    <div class="state-icon">
      <el-icon v-if="type === 'loading'" class="is-loading"><Loading /></el-icon>
      <el-icon v-else-if="type === 'error'"><CircleCloseFilled /></el-icon>
      <el-icon v-else><Box /></el-icon>
    </div>
    <div class="state-text">
      <div class="state-title">{{ title || (type === 'loading' ? '加载中…' : type === 'error' ? '加载失败' : '暂无数据') }}</div>
      <div v-if="description" class="state-desc">{{ description }}</div>
    </div>
    <div v-if="$slots.action" class="state-action"><slot name="action" /></div>
  </div>
</template>

<style scoped>
.state-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  padding: var(--sp-6) var(--sp-4);
  text-align: center;
  color: var(--color-text-secondary);
  background: var(--color-bg-surface);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-lg);
}
.state-block.compact {
  padding: var(--sp-4);
  border-style: solid;
  background: transparent;
}
.state-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  font-size: 22px;
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
}
.is-error .state-icon {
  color: var(--color-danger);
  background: var(--color-danger-weak);
  border-color: color-mix(in srgb, var(--color-danger) 30%, transparent);
}
.is-loading .state-icon {
  color: var(--color-primary);
  background: var(--color-primary-weak);
  border-color: color-mix(in srgb, var(--color-primary) 30%, transparent);
}
.is-empty .state-icon {
  color: var(--color-text-muted);
}
.state-title {
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--color-text-primary);
}
.state-desc {
  font-size: var(--font-xs);
  color: var(--color-text-muted);
  max-width: 420px;
  line-height: 1.6;
}
.state-action {
  margin-top: var(--sp-2);
}
</style>
