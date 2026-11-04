# 计划映射：本仓库 ↔《本月 Demo 详细计划》

图例：✅ demo 已跑通（simulator 上端到端验证）｜ 🐧 Linux 真实 Redroid 脚本/代码就绪（需宿主机验证）｜ 🧩 骨架就绪（可编译，生产再补）

## 一、验收清单 8 条对照（§5）

| # | 验收项 | 落地位置 | 状态 |
|---|---|---|---|
| 1 | 登录：账号密码登录成功 | `backend/app/routers/auth.py` · `frontend/src/views/Login.vue` | ✅ |
| 2 | 建机：一键创建/启动 10 台，显示 iOS 皮肤 | `routers/devices.py:batch_create` · `preview.py`(iOS 皮肤) · `views/Devices.vue` | ✅ |
| 3 | 开网页：每台浏览器打开指定网页 | `services.create_device`(target_url) · `orchestrator/*.open_url` | ✅ |
| 4 | 独立身份：抽查 3 台标识/IP/指纹各不同 | `fingerprint.py` · 指纹抽屉 `views/Devices.vue` | ✅（smoke §3 断言互不相同）|
| 5 | 投屏预览：Web & PC 多画面网格看 10 台 | `routers/ws.py`(preview) · `views/Grid.vue` · `pc-client/`(Electron 封装同页) | ✅ Web/PC · 🐧 真实帧走 minicap |
| 6 | 单台操控：实时操控浏览器 | `routers/control.py` · `views/Control.vue`(点击画面映射坐标) | ✅ |
| 7 | 批量同步：一键全部开同一网页并同步操作 | `routers/batch.py`(跨分辨率折算) · `views/Batch.vue` | ✅ |
| 8 | App 端 + 脚本：App 看设备操控；脚本跨设备回放 | `app-client/`(Kotlin) · `routers/scripts.py` · `views/Scripts.vue` | ✅ 脚本 · 🧩 App(需 Gradle 构建) |

> 一键验证：后端启动后运行 `cd backend && python -m tests.smoke`，逐条打印 §1–§8 结果。

## 二、逐日任务映射（D1–D20，§4）

### W1 云手机底座
| 日 | 任务 | 落地 | 状态 |
|---|---|---|---|
| D1 | 起 redroid + Chromium 开网页 | `orchestrator/redroid.py` · `deploy/redroid/start-instance.sh` | 🐧 |
| D2 | iOS 皮肤（Lawnchair+图标+壁纸+Dock） | `deploy/ios-skin/README.md` · `preview.py`(demo 皮肤) | 🐧 皮肤流程 · ✅ demo 观感 |
| D3 | 一机一码 + 浏览器指纹隔离 | `fingerprint.py`(设备标识+浏览器指纹) | ✅ |
| D4 | 容器编排 API（建/启/停/删/批量） | `routers/devices.py` · `services.py` | ✅ |
| D5 | 独立出口 IP / 代理位；验证不同 IP+指纹 | `fingerprint.py`(network) · `config.proxy_pool` · smoke §3 | ✅ |

### W2 群控投屏 + Web 管理
| 日 | 任务 | 落地 | 状态 |
|---|---|---|---|
| D6 | STF 部署 + 接 redroid | `deploy/stf/docker-compose.stf.yml` | 🐧 |
| D7 | 网页投屏 minicap + 控制 minitouch + 装 APK | `deploy/stf/` · `orchestrator/redroid.py`(adb) | 🐧 |
| D8 | Web 骨架：登录 JWT + 设备列表 + 分组 | `routers/auth.py,groups.py` · `views/Devices.vue` | ✅ |
| D9 | 设备生命周期 UI：启停/删/分组/改名/搜索 | `views/Devices.vue` | ✅ |
| D10 | 多设备网格预览 2×2/3×3/4×4 + 放大操控 | `views/Grid.vue` · `routers/ws.py` | ✅ |

### W3 批量 + 脚本 + App
| 日 | 任务 | 落地 | 状态 |
|---|---|---|---|
| D11 | 批量开 URL / 点击滑动输入 / 装 APK | `routers/batch.py` · `views/Batch.vue` | ✅ |
| D12 | 同步操控（1 控 N）+ 跨分辨率坐标适配 | `routers/batch.py:_scale` · `views/Batch.vue` | ✅ |
| D13 | 脚本录制回放（开网页→操作）+ 报告 | `routers/scripts.py` · `views/Control.vue`(录制) · `views/Scripts.vue`(回放报告) | ✅（真实 CV 用 Airtest 时接运行时）|
| D14 | 安卓 App：登录+设备列表+单设备投屏 | `app-client/`(login/devices/detail) | 🧩 |
| D15 | App：分组+批量入口+基础操控 | `app-client/ui/batch` | 🧩 |

### W4 PC 客户端 + 集成 + 演示
| 日 | 任务 | 落地 | 状态 |
|---|---|---|---|
| D16 | PC/Windows 群控客户端（Electron 出 exe） | `pc-client/`(main.js + electron-builder.yml) | 🧩（需 npm 构建）|
| D17 | 三端连同一后端，数据一致 | Web/PC/App 共用 `/api` 契约 | ✅ 契约一致 |
| D18 | iOS 皮肤打磨 + 端到端演示串通 | `tests/smoke.py`(闭环) · `deploy/ios-skin/` | ✅ 闭环 |
| D19 | 演示环境部署 + 10–20 台压测 | `docker-compose.yml` · `deploy/scripts/density-test.sh` | ✅ compose · 🐧 密度压测 |
| D20 | 彩排 + 录屏 + 交付文档 | `docs/`(架构+映射) · 各 README | ✅ 文档 |

## 三、本月不做（OUT，§2）——本仓库同样未做，符合范围

500 台规模化编排(k8s)、系统级 iOS ROM 深度复刻、数据看板/报表/四级权限、云摄像头/RTMP、深度风控持续对抗、等保/硬件采购。以上留作后续路线图（见方案包《逐日实施方案_开源优先》D21–D120）。

## 四、从 demo 到真实 Redroid 的切换点

唯一开关：`CLOUD_DEVICE_BACKEND=simulator → redroid`。切换后：
- 建机走真实 Docker 容器（`deploy/redroid/start-instance.sh` 的等价逻辑在 `orchestrator/redroid.py`）；
- 指纹以 props 注入容器（`fingerprint.redroid_props`）；
- 预览/操控走 adb（生产替换为 minicap/minitouch/scrcpy）。
业务代码、API 契约、前端、三端客户端**零改动**。
