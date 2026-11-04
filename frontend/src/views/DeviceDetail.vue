<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/client'
import { useDevices, SKIN_PHASE_TEXT } from '../stores/devices'
import { useAuth } from '../stores/auth'
import PhoneFrame from '../components/PhoneFrame.vue'

const route = useRoute()
const router = useRouter()
const store = useDevices()
const auth = useAuth()

const id = computed(() => Number(route.params.id))
const detail = ref(null)
const apps = ref([])
const loading = ref(false)

const statusType = { running: 'success', stopped: 'info', creating: 'warning', error: 'danger' }
const statusText = { running: '运行中', stopped: '已停止', creating: '创建中', error: '异常' }

const dev = computed(() => detail.value?.fingerprint?.device || {})
const browser = computed(() => detail.value?.fingerprint?.browser || {})
const network = computed(() => detail.value?.fingerprint?.network || {})

// iOS 皮肤查看器 + 一键换肤（原创设计稿：7 屏 × 3 主题）
const skinScreen = ref('home')
const skinTheme = ref('ios')
const skinThemes = ref([])
const skinFrame = ref('')
const skinApplying = ref(false)
async function loadSkin() {
  try {
    const { data } = await http.get(`/skin/${id.value}`, {
      params: { screen: skinScreen.value, theme: skinTheme.value },
    })
    skinFrame.value = data.frame
  } catch {
    skinFrame.value = ''
  }
}
async function applySkinOne() {
  skinApplying.value = true
  try {
    await http.post(`/skin/${id.value}`, { theme: skinTheme.value })
    const label = skinThemes.value.find((t) => t.key === skinTheme.value)?.label || skinTheme.value
    ElMessage.success(`已换肤：${label} · 预览即时生效，真机后台落地中（下方显示进度）`)
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '换肤失败')
  } finally {
    skinApplying.value = false
  }
}

function fmtUptime(s) {
  if (s == null) return '—（未运行）'
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const parts = []
  if (d) parts.push(`${d}天`)
  if (d || h) parts.push(`${h}小时`)
  if (d || h || m) parts.push(`${m}分`)
  parts.push(`${sec}秒`)
  return parts.join(' ')
}

async function load() {
  loading.value = true
  try {
    const [d, a] = await Promise.all([
      http.get(`/devices/${id.value}/detail`),
      http.get(`/devices/${id.value}/apps`),
    ])
    detail.value = d.data
    apps.value = a.data.apps || []
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载设备详情失败')
  } finally {
    loading.value = false
  }
  await loadShares()
}

// ---------- 设备共享（V3，同租户） ----------
const shares = ref([])
const shareCandidates = ref([])
const shareTarget = ref(null)
const shareLoading = ref(false)
const shareBusy = ref(false)
const shareError = ref('')

const canManageShare = computed(() => {
  if (!detail.value) return false
  if (auth.isAdmin) return true
  return detail.value.owner_id != null && detail.value.owner_id === auth.user?.id
})
const activeShares = computed(() => shares.value.filter((s) => s.active))

async function loadShares() {
  shareError.value = ''
  shares.value = []
  shareCandidates.value = []
  if (!canManageShare.value) return
  shareLoading.value = true
  try {
    const [s, c] = await Promise.all([
      http.get(`/devices/${id.value}/shares`),
      http.get(`/devices/${id.value}/share-candidates`),
    ])
    shares.value = s.data || []
    shareCandidates.value = c.data || []
  } catch (e) {
    shareError.value = e?.response?.data?.detail || '加载共享设置失败'
  } finally {
    shareLoading.value = false
  }
}

async function grantShare() {
  if (!shareTarget.value) return
  shareBusy.value = true
  try {
    await http.post(`/devices/${id.value}/shares`, { user_id: shareTarget.value })
    ElMessage.success('已共享（viewer 级可见性，不提升写权限）')
    shareTarget.value = null
    await loadShares()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '共享失败')
  } finally {
    shareBusy.value = false
  }
}

async function revokeShare(row) {
  try {
    await ElMessageBox.confirm(
      `撤销对「${row.username}」的共享？撤销后立即失效。`,
      '撤销共享',
      { type: 'warning', confirmButtonText: '撤销', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  shareBusy.value = true
  try {
    await http.delete(`/devices/${id.value}/shares/${row.id}`)
    ElMessage.success('已撤销共享')
    await loadShares()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '撤销失败')
  } finally {
    shareBusy.value = false
  }
}

onMounted(async () => {
  await load()
  try {
    skinThemes.value = (await http.get('/skin/themes')).data.themes
  } catch {
    skinThemes.value = [{ key: 'ios', label: 'iOS 风' }]
  }
  skinTheme.value = detail.value?.skin || 'ios'
  loadSkin()
  store.refreshSkinApplying()
  // 与「操控页」一致：订阅预览帧（低频，仅本页展示）
  store.subscribePreviews([id.value], 2)
})
onBeforeUnmount(() => store.subscribePreviews([], 1))
</script>

<template>
  <div class="page" v-loading="loading && !detail">
    <div class="toolbar">
      <el-button :icon="'ArrowLeft'" @click="router.push(route.query.from === 'grid' ? '/grid' : '/devices')">返回</el-button>
      <span v-if="detail" style="font-weight: 600">{{ detail.name }}</span>
      <el-tag v-if="detail" :type="statusType[detail.status]" size="small">
        {{ statusText[detail.status] || detail.status }}
      </el-tag>
      <el-tag v-if="detail">{{ dev.model }}</el-tag>
      <div class="spacer"></div>
      <el-button :icon="'Refresh'" @click="load">刷新</el-button>
    </div>

    <div v-if="detail" style="display: flex; gap: 26px; padding: 8px 0; align-items: flex-start">
      <!-- 左：实时预览 -->
      <div style="width: 268px; flex: none">
        <PhoneFrame :device="detail" :frame="store.frames[id]" />
        <div style="text-align: center; color: #86868b; font-size: 12px; margin-top: 8px">
          实时预览（低频刷新）
        </div>

        <!-- iOS 皮肤设计 + 一键换肤（原创矢量，非 Apple 素材） -->
        <div style="font-weight: 600; margin: 18px 0 8px">iOS 皮肤设计 · 一键换肤</div>
        <el-radio-group v-model="skinTheme" size="small" @change="loadSkin" style="margin-bottom: 8px; flex-wrap: wrap">
          <el-radio-button v-for="t in skinThemes" :key="t.key" :value="t.key">{{ t.label }}</el-radio-button>
        </el-radio-group>
        <el-radio-group v-model="skinScreen" size="small" @change="loadSkin" style="margin-bottom: 10px; flex-wrap: wrap">
          <el-radio-button value="home">主屏</el-radio-button>
          <el-radio-button value="today">今天</el-radio-button>
          <el-radio-button value="applibrary">资源库</el-radio-button>
          <el-radio-button value="spotlight">搜索</el-radio-button>
          <el-radio-button value="lock">锁屏</el-radio-button>
          <el-radio-button value="control">控制中心</el-radio-button>
          <el-radio-button value="browser">Safari</el-radio-button>
        </el-radio-group>
        <div class="phone" style="cursor: default">
          <img v-if="skinFrame" :src="skinFrame" alt="iOS 皮肤" />
        </div>
        <el-button
          type="primary"
          size="small"
          :loading="skinApplying"
          style="width: 100%; margin-top: 10px"
          @click="applySkinOne"
        >应用「{{ skinThemes.find((t) => t.key === skinTheme)?.label || skinTheme }}」到本机</el-button>
        <div
          v-if="store.skinProgress[id]"
          style="text-align: center; font-size: 12px; margin-top: 8px"
          :style="{ color: store.skinProgress[id].phase === 'failed' ? '#f56c6c' : '#e6a23c' }"
        >
          <el-icon
            v-if="!['done', 'failed'].includes(store.skinProgress[id].phase)"
            class="is-loading"
            style="vertical-align: -2px; margin-right: 3px"
          ><Loading /></el-icon>
          真机落地：{{ SKIN_PHASE_TEXT[store.skinProgress[id].phase] || store.skinProgress[id].phase }}
        </div>
        <div style="text-align: center; color: #86868b; font-size: 12px; margin-top: 8px">
          皮肤级苹果 UI · 原创矢量设计稿 · 当前皮肤 {{ detail.skin || '原生安卓' }}
        </div>
      </div>

      <!-- 右：聚合信息 -->
      <div style="flex: 1; min-width: 0">
        <!-- 运行概览 -->
        <el-card shadow="never" style="margin-bottom: 14px">
          <div style="font-weight: 600; margin-bottom: 12px">运行概览</div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="状态">
              <el-tag :type="statusType[detail.status]" size="small">
                {{ statusText[detail.status] || detail.status }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="运行时长">{{ fmtUptime(detail.uptime_seconds) }}</el-descriptions-item>
            <el-descriptions-item label="出口 IP">{{ network.exit_ip || '—' }}</el-descriptions-item>
            <el-descriptions-item label="ADB 端口">{{ detail.adb_port ?? '—' }}</el-descriptions-item>
            <el-descriptions-item label="归属者">{{ detail.owner_name || (detail.owner_id ? `用户#${detail.owner_id}` : '平台设备') }}</el-descriptions-item>
            <el-descriptions-item label="分辨率">{{ detail.width }} × {{ detail.height }} @ {{ detail.dpi }}dpi</el-descriptions-item>
            <el-descriptions-item label="已装应用">{{ detail.installed_app_count }} 个</el-descriptions-item>
            <el-descriptions-item label="当前页面" :span="2">
              <span style="color: #007aff">{{ detail.current_url || '主屏（无网页）' }}</span>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- 设备标识 -->
        <el-card shadow="never" style="margin-bottom: 14px">
          <div style="font-weight: 600; margin-bottom: 12px">设备标识（一机一码）</div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="品牌">{{ dev.brand }}</el-descriptions-item>
            <el-descriptions-item label="机型">{{ dev.model }}</el-descriptions-item>
            <el-descriptions-item label="Android ID">{{ dev.android_id }}</el-descriptions-item>
            <el-descriptions-item label="序列号">{{ dev.serialno }}</el-descriptions-item>
            <el-descriptions-item label="IMEI">{{ dev.imei }}</el-descriptions-item>
            <el-descriptions-item label="MAC">{{ dev.mac }}</el-descriptions-item>
            <el-descriptions-item label="Android 版本" :span="2">{{ dev.android_version }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- 浏览器指纹 -->
        <el-card shadow="never" style="margin-bottom: 14px">
          <div style="font-weight: 600; margin-bottom: 12px">浏览器指纹</div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="User-Agent">{{ browser.user_agent }}</el-descriptions-item>
            <el-descriptions-item label="时区 / 语言">{{ browser.timezone }} / {{ browser.language }}</el-descriptions-item>
            <el-descriptions-item label="WebGL">{{ browser.webgl_vendor }} · {{ browser.webgl_renderer }}</el-descriptions-item>
            <el-descriptions-item label="Canvas 噪声">{{ browser.canvas_noise_seed }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- 网络 -->
        <el-card shadow="never" style="margin-bottom: 14px">
          <div style="font-weight: 600; margin-bottom: 12px">网络</div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="出口 IP">{{ network.exit_ip || '—' }}</el-descriptions-item>
            <el-descriptions-item label="代理">{{ network.proxy || '直连' }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- 设备共享（同租户，V3） -->
        <el-card v-if="canManageShare" v-loading="shareLoading" shadow="never" style="margin-bottom: 14px">
          <div style="font-weight: 600; margin-bottom: 10px">设备共享（同租户）</div>
          <el-alert
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom: 10px"
            title="共享授予 viewer 级可见性，不提升写权限（写操作仍要求 operator+）；撤销后立即失效。"
          />
          <div v-if="shareError" style="color: var(--color-danger); font-size: 12px; margin-bottom: 8px">
            {{ shareError }}
          </div>
          <el-table v-if="activeShares.length" :data="activeShares" border size="small">
            <el-table-column prop="username" label="已共享用户" />
            <el-table-column prop="role" label="角色" width="100" />
            <el-table-column prop="granted_by" label="授予人" width="120" />
            <el-table-column label="共享时间" width="180">
              <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
            </el-table-column>
            <el-table-column label="操作" width="90">
              <template #default="{ row }">
                <el-button link type="danger" :disabled="shareBusy" @click="revokeShare(row)">撤销</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else-if="!shareLoading && !shareError" description="尚未共享给其他用户" :image-size="64" />
          <div style="display: flex; gap: 8px; margin-top: 10px; align-items: center">
            <el-select
              v-model="shareTarget"
              placeholder="选择同租户用户"
              size="small"
              style="width: 220px"
              filterable
              :disabled="shareBusy"
            >
              <el-option
                v-for="u in shareCandidates"
                :key="u.id"
                :label="`${u.username}（${u.role}）`"
                :value="u.id"
              />
            </el-select>
            <el-button type="primary" size="small" :disabled="!shareTarget || shareBusy" @click="grantShare">
              共享
            </el-button>
          </div>
        </el-card>

        <!-- 已装应用 -->
        <el-card shadow="never">
          <div style="font-weight: 600; margin-bottom: 12px">
            已装应用
            <el-tag size="small" type="info" style="margin-left: 6px">{{ apps.length }}</el-tag>
          </div>
          <el-table v-if="apps.length" :data="apps.map((p, i) => ({ i: i + 1, pkg: p }))" border stripe size="small" max-height="360">
            <el-table-column prop="i" label="#" width="60" />
            <el-table-column prop="pkg" label="包名" />
          </el-table>
          <el-empty v-else description="未获取到已装应用" :image-size="80" />
        </el-card>
      </div>
    </div>
  </div>
</template>
