import { createRouter, createWebHashHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuth } from '../stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/Login.vue') },
  {
    path: '/',
    component: () => import('../layouts/MainLayout.vue'),
    redirect: '/devices',
    children: [
      { path: 'dashboard', name: 'dashboard', meta: { title: '数据看板' }, component: () => import('../views/Dashboard.vue') },
      { path: 'devices', name: 'devices', meta: { title: '设备管理' }, component: () => import('../views/Devices.vue') },
      { path: 'grid', name: 'grid', meta: { title: '多画面预览' }, component: () => import('../views/Grid.vue') },
      { path: 'batch', name: 'batch', meta: { title: '批量操控' }, component: () => import('../views/Batch.vue') },
      { path: 'scripts', name: 'scripts', meta: { title: '脚本回放' }, component: () => import('../views/Scripts.vue') },
      { path: 'tasks', name: 'tasks', meta: { title: '任务调度' }, component: () => import('../views/Tasks.vue') },
      { path: 'alerts', name: 'alerts', meta: { title: '告警监控' }, component: () => import('../views/Alerts.vue') },
      { path: 'reports', name: 'reports', meta: { title: '统计报表' }, component: () => import('../views/Reports.vue') },
      { path: 'downloads', name: 'downloads', meta: { title: '下载中心' }, component: () => import('../views/DownloadCenter.vue') },
      { path: 'logs', name: 'logs', meta: { title: '设备日志' }, component: () => import('../views/Logs.vue') },
      { path: 'files', name: 'files', meta: { title: '文件互传' }, component: () => import('../views/FileManager.vue') },
      { path: 'cloud-disk', name: 'cloud-disk', meta: { title: '云盘' }, component: () => import('../views/CloudDisk.vue') },
      { path: 'ips', name: 'ips', meta: { title: 'IP 资源池' }, component: () => import('../views/IpPool.vue') },
      { path: 'users', name: 'users', meta: { title: '用户管理', minRole: 'admin' }, component: () => import('../views/Users.vue') },
      { path: 'audit', name: 'audit', meta: { title: '操作审计', minRole: 'admin' }, component: () => import('../views/Audit.vue') },
      { path: 'apps', name: 'apps', meta: { title: '应用管理' }, component: () => import('../views/AppManager.vue') },
      { path: 'app-library', name: 'app-library', meta: { title: '应用库' }, component: () => import('../views/AppLibrary.vue') },
      { path: 'push-jobs', name: 'push-jobs', meta: { title: '推送进度' }, component: () => import('../views/PushProgress.vue') },
      { path: 'groups', name: 'groups', meta: { title: '分组管理' }, component: () => import('../views/Groups.vue') },
      { path: 'device/:id', name: 'control', meta: { title: '单机操控' }, component: () => import('../views/Control.vue') },
      { path: 'detail/:id', name: 'detail', meta: { title: '设备详情' }, component: () => import('../views/DeviceDetail.vue') },
    ],
  },
]

const router = createRouter({ history: createWebHashHistory(), routes })

router.beforeEach(async (to) => {
  const auth = useAuth()
  if (to.name !== 'login' && !auth.isAuthed) return { name: 'login' }
  if (to.name === 'login' && auth.isAuthed) return { name: 'devices' }

  // 按角色的路由白名单：Users / Audit 仅 admin 及以上
  const minRole = to.meta?.minRole
  if (minRole) {
    // 刷新后 store 里只有 token、没有 user，先拉一次当前用户再判断
    if (!auth.user) {
      try {
        await auth.fetchMe()
      } catch {
        return { name: 'login' }
      }
    }
    if (!auth.can(minRole)) {
      ElMessage.warning('当前角色无权限，请联系管理员')
      return { name: 'devices' }
    }
  }
})

export default router
