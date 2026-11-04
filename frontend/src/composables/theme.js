/**
 * 明暗主题（V2-2）
 * - 模式：light / dark / system（默认 dark，浅色仍可切换）
 * - 暗色只切换 html.dark + 同一批 tokens.css 变量，不维护第二套样式表
 * - localStorage 持久化；system 模式下监听系统偏好变化
 */
import { computed, ref } from 'vue'

const KEY = 'theme.mode'
const VALID = ['light', 'dark', 'system']
const stored = localStorage.getItem(KEY)
// V6：默认深色（品牌蓝深色体系），仍保留浅色/跟随系统切换
const mode = ref(VALID.includes(stored) ? stored : 'dark')
const systemDark = ref(window.matchMedia('(prefers-color-scheme: dark)').matches)
const effective = computed(() => (mode.value === 'system' ? (systemDark.value ? 'dark' : 'light') : mode.value))

function apply() {
  const dark = effective.value === 'dark'
  document.documentElement.classList.toggle('dark', dark)
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
}

function setMode(next) {
  if (!VALID.includes(next)) return
  mode.value = next
  localStorage.setItem(KEY, next)
  apply()
}

const media = window.matchMedia('(prefers-color-scheme: dark)')
media.addEventListener('change', (e) => {
  systemDark.value = e.matches
  if (mode.value === 'system') apply()
})

export function initTheme() {
  apply()
}

export function useTheme() {
  return { mode, effective, setMode }
}
