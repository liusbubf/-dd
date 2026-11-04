# 变更记录

按功能颗粒度记录（与 git 提交对应）。

## 主流程 Demo（初版）
- 后端：FastAPI 平台核心 —— JWT 鉴权、设备/分组、可插拔编排（simulator/redroid）、一机一码、单机操控、批量/同步、脚本录制回放、WebSocket 实时推送。
- 前端：Vue3 + Element Plus 管理控制台 —— 登录/设备管理/多画面预览/单机操控/批量操控/脚本回放。
- 部署：Docker Compose + Redroid 启动/批量/密度脚本 + STF 集成 + 宿主机准备。
- 客户端：PC（Electron 封装）+ Android（Kotlin/Compose 骨架）。
- 文档：技术文档、架构、计划映射、W1–W2 PoC。
- 冒烟测试覆盖 8 条验收清单，simulator 模式全绿。

## 真机接入（redroid on Apple Silicon）
- Lima arm64 Ubuntu VM 内跑真实 Redroid Android 12（64only 镜像，规避 32 位 zygote 崩溃）。
- 后端 redroid 模式跑在 VM 内，Mac 经 ssh 隧道接入；`deploy/scripts/{vm-run-backend,connect-vm-redroid}.sh` 一键接入。
- 扩容至 10 台真机，8 条验收全达标；密度上限 8G≈10 台（~606MiB/台）；`deploy/scripts/redroid-benchmark.sh`。
- 真机控制完善：Home 用 HOME intent、新增最近/唤醒键。
- 实时渲染：单机页高频轮询（~5–12fps，`/screenshot` ~64ms），点击到刷新 ~400ms。

## 扩展模块
- 数据看板：`/api/metrics/*` + Dashboard 页。
- 告警监控：`/api/alerts/*`（即时计算）+ Alerts 页。
- 任务调度（7.3）：`/api/tasks/*` + ScheduledTask + 后台调度器 + Tasks 页；真机 run-now 2/2。
- 设备详情（GM-003）：`/api/devices/{id}/detail|apps` + 编排 `list_apps` + DeviceDetail 页；真机 97 个已装包。
- iOS 皮肤：真机桌面 iOS 观感（壁纸/圆角/4 列网格/Dock），`deploy/ios-skin/`。
- 低延迟投屏（scrcpy）：操控页「高清投屏 12fps」+ scrcpy CLI H.264 验证 + **ws-scrcpy 浏览器 H.264 流跑通并集成**（操控页「scrcpy 投屏」入口），`deploy/scrcpy/`。

## 平台增强（RBAC / 脚本 / 报表 / 日志 / 分辨率）
- CP-007 分辨率/DPI 运行时切换：编排 `set_display` + `/control/display` + 操控页 UI；真机 `Override 1080x1920@480` 验证。
- RBAC 权限体系（PC-301/302）：四级角色 + `require_role` + 用户管理 + 操作审计 + 菜单角色门控；viewer 403 / admin 200 验证。
- 脚本引擎增强（GM-202/205）：可视化编辑（增删改/排序）+ 模板库(4) + 导入导出 + `loop`/`wait` 逻辑控制。
- 统计报表（PC-204）：`/reports/summary` + 带 BOM 的 CSV 导出。
- 设备日志（7.5.3）：`/devices/{id}/logcat` 走编排 `list_logcat`；真机 50 行真实 logcat。

## 一键换肤真机完整落地（Lawnchair iOS 桌面 + 实时进度）
- 真机换肤补全：`apply_skin` 从「仅壁纸+重启」升级为 `apply-ios-skin.sh` 全流程 API 移植 —— 装 Lawnchair 1.2.0.1884（`deploy/ios-skin/fetch-lawnchair.sh` 下载官方 Releases 原版到 `app/skins/`，缺失降级仅壁纸）+ `pm grant` 防首启弹窗 + set-home → 重排 launcher.db（iOS 4 列网格 + Dock4，进程内 sqlite3）→ 主题壁纸 → 容器重启 → 开机后合并 squircle/网格偏好。
- 换肤落地进度实时提示：WS 广播 `skin_progress`（排队/装启动器/布置桌面/写壁纸/重启生效中/配置主题/完成/失败）+ `GET /api/skin/applying` 补齐；前端设备列表「皮肤」列与详情页实时展示，终态 6s 自动消失。
- 真机验证：device2/3 fresh 安装路径全通，开机即 iOS 风桌面（`docs/screenshots/真机_iOS皮肤_一键换肤API.png`）。

## 真机桌面 = 设计稿 1:1（多 agent 工作流）
- 设计稿资产同源渲染：gen-design-icons.py / gen-theme-wallpapers.py 从 preview.py 渲染 3 主题 × 20 图标 PNG + 9 张分档壁纸（Chrome 无头）；Dock 毛玻璃底板与双页圆点画进壁纸（Lawnchair 无此功能，静态壁纸视觉等效）。
- 真机桌面重写：ios_layout.py 设计稿 20 条目布局表；favorites 全部 itemType=1 快捷方式 + 图标 BLOB（真机探针验证像素级原样）；壁纸按设备 seed 选 rid 分档与预览同款；Lawnchair 偏好追加隐藏日期 widget/Dock 透明/隐藏箭头（dex 扫键 + 逐键真机验证）。
- 健壮性：apply_skin adb 可达性预检（不可达明确失败，不静默降级）；显式 adb start-server 规避后台任务挂死；新装设备 4×4 网格删行 → 偏好合并后二次写网格。
- 验证：4 台真机全部与设计稿一致（真机_iOS皮肤_设计稿对比.png / 真机_iOS皮肤_全设备.png）。

## 皮肤收尾（三主题真机 + 手势导航 + 全生命周期）
- 三主题真机验证：深色毛玻璃/暖阳渐变经管理台 UI 下发落地（Playwright 实测 UI 链路与皮肤列进度）。
- iOS 手势导航条：换肤时启用 gestural navbar overlay，三键导航 → 小白条。
- 全生命周期：新建机 → UI 换肤 → 进度提示 → 3 分钟完整 iOS 桌面；行内换肤允许重落当前主题。
- 冒烟保护：tests/smoke.py 拒绝 redroid 真机后端（曾误建 10 台真容器打爆 VM 内存），需 --i-know-redroid。
- 健壮性：apply_skin adb 可达性预检修复批量场景静默降级（表现为「换肤没效果」）。

## v1.1 健壮性与真机视觉修复（2026-07-27）

### 修复：adb 失败不再静默降级（重要）
一整类「故障被藏起来」的问题。触发现场：6 台真机中 3 台 adb 断连，但管理台一切正常 ——
预览有画面、批量报 6/6 成功、状态运行中，实际那 3 台早已失联。

- 根因：`RedroidBackend._adb()` 忽略返回码，整个 adb 调用面（20+ 处）都在吞失败。
  其中 `screenshot()` 取帧失败会**回退成平台层 SVG 皮肤图**，画面看着完全正常；
  且「主屏未开网页」那条分支根本不碰 adb，设备死了照样出图。
- 修法集中在 `_adb()` 一个卡点：区分「传输层错误」与「命令本身失败」；传输层错误
  **先自愈**（`adb connect` + 轮询就绪 ~2s），仍失败抛 `DeviceUnreachable`。
- `screenshot()` 增加 `_ensure_alive()` 前置体检（TTL 5s，取帧最高 12fps 不能每帧体检）。
- `open_url()` 改为先下发成功再写 `current_url`（否则失联设备列表仍显示「当前页面」）。
- `list_apps/list_logcat/list_files` 失败改抛 `DeviceCommandError`，不再返回空列表
  （空列表会把「读不到」显示成「没有应用 / 没有日志 / 空目录」）。
- 路由层：`DeviceUnreachable`→503（带 adb connect 提示）、`DeviceCommandError`→502；
  WS 预览循环单台失败不再中断整条循环（原实现一台掉线会让所有人画面全停），
  改推 `device_unreachable` 消息。
- 坑：adb 真实报文是 `error: device 'localhost:5561' not found`，序列号夹在中间，
  匹配 `"device not found"` 永远不命中 —— 早期写法因此从未触发自愈重连。改用
  「行首 `error:`/`adb:` + 传输关键词」两段判据，且排除设备侧 `sh: xxx: not found`。
- 真机验证：断连→自愈返回真机 PNG；容器停掉→503 `device offline`；
  批量含 1 台死机→3 成功/1 失败并列出原因（修复前 4/4 全成功）。

### 修复：登录失效卡空白页
token 过期后页面一片空白，既不提示也不跳登录页。根因是 401 拦截器只删了 localStorage
没清 Pinia store，路由守卫读的是 store → 把 `/login` 又弹回 `/devices`。
现在：清 store + 提示「登录状态已失效，请重新登录」+ 跳登录页，并发 401 节流只提示一次；
另加 503 设备失联提示（按 device_id 节流 10s，避免高频取帧刷屏）。

### 新增：通知栏 / 控制中心
操控页「下滑」是页面滚动（30%→80%），起点没压在状态栏上，永远拉不出通知栏。
新增 `notifications`/`quicksettings`/`collapse` 三个动作，走 AOSP `cmd statusbar`
（不依赖起点像素，且启用 iOS 手势导航条后手势更易被吞）；原按钮改名「上滑/下滑滚动」。

### 修复：真机 Dock 底板错位 + 页面圆点数量
- Dock 底板：Android 显示壁纸时是**放大 1.1 倍居中裁剪**（留视差余量），而底板坐标按
  1:1 算 → 左右溢出屏幕、上下与图标错位。用壁纸内已知图元（页面圆点）标定该变换，
  720x1280 与 1080x1920 两种分辨率均吻合；改为经 `_wx/_wy` 逆变换按「屏幕上想要的位置」
  书写坐标。实测底板 y=1026..1172 对图标带 y=1042..1156，上下留白各 16px 完全对称。
- 页面圆点：画了 2 个但主屏只有 1 页（`ios_layout` 16 个图标全在 screen=0，左右滑
  没有第二页可去）。改为按实际页数渲染，预览 SVG 与真机壁纸两处同步。

### 新增：真机验收核验脚本
`backend/acceptance_live.py` —— 补上「文档引用了但仓库里从未存在」的缺口。
非破坏性（不建机不删机、跑完还原设备原网页），逐条核验 8 项验收并打印实测数值；
§5 专门检出「有画面但其实是失联」的伪装。当前 6 台真机：7 通过 / 0 失败 / 1 跳过。

### 新增文档
- `docs/部署搭建手册_x86服务器_中国大陆.md` —— 面向甲方运维的搭建方案：x86 服务器选型
  （Xeon 无核显、NVIDIA 不可用、ARM 转译授权）、内核 binder 红线、国内镜像加速与离线部署、
  三条部署路径、生产加固、16 条 FAQ。
- `docs/X86云手机平台_项目交付说明书_v1.1.docx` —— 甲方交付说明书（技术/功能/进度）。

证据截图见 `docs/screenshots/`。

