<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'

const router = useRouter()
const auth = useAuth()
const username = ref('')
const password = ref('')
const loading = ref(false)
const agreeTerms = ref(false)

// ---- 图形验证码（V2-1）----
const captcha = ref(null) // { captcha_id, image, expires_in }
const captchaCode = ref('')
const captchaLoading = ref(false)
const captchaError = ref('')

async function loadCaptcha() {
  captchaLoading.value = true
  captchaError.value = ''
  try {
    const { data } = await api.captcha()
    captcha.value = data
    captchaCode.value = ''
  } catch (e) {
    captcha.value = null
    captchaError.value = e?.response?.data?.detail || '验证码加载失败'
  } finally {
    captchaLoading.value = false
  }
}

onMounted(loadCaptcha)

const captchaHint = computed(() =>
  captcha.value ? `验证码 ${Math.round(captcha.value.expires_in / 60)} 分钟有效，点击可更换` : '',
)

function fmtLast(t) {
  if (!t) return ''
  const d = new Date(t)
  return Number.isNaN(d.getTime()) ? String(t) : d.toLocaleString()
}

function showTerms() {
  ElMessageBox.alert(
    '【用户协议与服务条款】\n\n' +
    '1. 本平台仅用于软件兼容性测试、自动化测试、授权的红蓝对抗、开发者研究等合法用途。\n' +
    '2. 禁止将本平台用于以下非法用途：\n' +
    '   - 绕过目标网站风控/反作弊检测\n' +
    '   - 破解软件或系统安全机制\n' +
    '   - 未经授权的红蓝对抗\n' +
    '   - 欺诈、赌博、洗钱等违法犯罪活动\n' +
    '3. 如违反上述条款，平台有权立即封禁账号和云机，无需另行通知。\n' +
    '4. 用户应遵守各平台的服务条款、隐私要求和安全政策。\n' +
    '5. 本平台保留对非法使用行为的追溯和追责权利。\n\n' +
    '点击"同意"即表示您已阅读并接受本协议的全部内容。',
    '用户协议与服务条款',
    {
      confirmButtonText: '我已阅读并同意',
      dangerouslyUseHTMLString: false,
      customClass: 'terms-dialog'
    }
  ).catch(() => {})
}

async function submit() {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名与密码')
    return
  }
  if (!captcha.value) {
    ElMessage.warning('验证码未加载，请刷新')
    loadCaptcha()
    return
  }
  if (!captchaCode.value.trim()) {
    ElMessage.warning('请输入图形验证码')
    return
  }
  if (!agreeTerms.value) {
    ElMessage.warning('请先阅读并同意用户协议与服务条款')
    return
  }
  loading.value = true
  try {
    const data = await auth.login(username.value, password.value, {
      captcha_id: captcha.value.captcha_id,
      captcha_code: captchaCode.value.trim(),
    })
    const last = data.last_login
    if (last) {
      const parts = [fmtLast(last.at)]
      if (last.ip) parts.push(`IP ${last.ip}`)
      if (last.location) parts.push(last.location)
      await ElMessageBox.alert(parts.join(' · '), '上次登录', { confirmButtonText: '继续' }).catch(() => {})
    } else {
      ElMessage.success('登录成功（首次登录）')
    }
    router.push('/devices')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '登录失败')
    // 验证码一次性：失败后必须换一张
    await loadCaptcha()
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-bg-orb orb-1"></div>
    <div class="login-bg-orb orb-2"></div>
    <div class="login-card">
      <div class="brand-row">
        <div class="brand-icon">📱</div>
        <div>
          <div class="login-title">X86 云手机平台</div>
          <div class="login-sub">企业级云手机群控管理中心</div>
        </div>
      </div>

      <div class="login-panel">
        <div class="panel-header">账户登录</div>
        <el-form @submit.prevent="submit">
          <el-form-item>
            <el-input v-model="username" placeholder="用户名" size="large" :prefix-icon="'User'" @keyup.enter="submit" />
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="password"
              type="password"
              placeholder="密码"
              size="large"
              show-password
              :prefix-icon="'Lock'"
              @keyup.enter="submit"
            />
          </el-form-item>

          <el-form-item>
            <div class="captcha-row">
              <el-input
                v-model="captchaCode"
                placeholder="图形验证码"
                size="large"
                maxlength="8"
                :prefix-icon="'Key'"
                @keyup.enter="submit"
              />
              <div class="captcha-box" :title="captchaHint" @click="loadCaptcha">
                <el-skeleton v-if="captchaLoading" :rows="1" animated />
                <div v-else-if="captchaError" class="captcha-error" @click.stop="loadCaptcha">
                  <span>加载失败</span>
                  <span class="captcha-refresh">重试</span>
                </div>
                <img v-else-if="captcha" :src="captcha.image" alt="图形验证码，点击刷新" />
              </div>
              <el-button text :loading="captchaLoading" @click="loadCaptcha">换一张</el-button>
            </div>
          </el-form-item>

          <el-button
            type="primary"
            native-type="submit"
            size="large"
            class="login-btn"
            :loading="loading"
            @click="submit"
          >
            登 录
          </el-button>
        </el-form>

        <div class="terms-agreement">
          <el-checkbox v-model="agreeTerms">
            我已阅读并同意
            <a href="#" @click.prevent="showTerms">《用户协议》</a>
            和
            <a href="#" @click.prevent="showTerms">《服务条款》</a>
          </el-checkbox>
        </div>
      </div>

      <div class="login-footer">
        <div class="chip">演示账号</div>
        <div class="demo-row"><span>管理员</span><strong>admin / admin123</strong></div>
        <div class="demo-row"><span>运营账号</span><strong>demo / demo123</strong></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.captcha-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
}
.captcha-row :deep(.el-input) {
  flex: 1;
  min-width: 0;
}
.captcha-box {
  flex: none;
  width: 120px;
  height: 44px;
  border-radius: var(--radius-md);
  overflow: hidden;
  background: #f4f7fc;
  border: 1px solid rgba(255, 255, 255, 0.18);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.captcha-box img {
  width: 100%;
  height: 100%;
  display: block;
}
.captcha-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-1);
  font-size: var(--font-xs);
  color: var(--color-danger);
}
.captcha-refresh {
  color: #8fb4ff;
  cursor: pointer;
}
.terms-agreement {
  margin-top: var(--sp-3);
  padding: var(--sp-2) var(--sp-3);
  background: rgba(255, 255, 255, 0.05);
  border-radius: var(--radius-md);
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}
.terms-agreement a {
  color: var(--color-primary);
  text-decoration: none;
  margin: 0 2px;
}
.terms-agreement a:hover {
  text-decoration: underline;
}
</style>
