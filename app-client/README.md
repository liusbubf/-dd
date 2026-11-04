# App 客户端（Android · Kotlin + Jetpack Compose）

X86 云手机平台的安卓 App 客户端（本月计划 **D14–D15**）：登录 + 设备列表 + 投屏预览 + 单台基础操控 + 批量操作。
与 Web 端、PC 端**复用同一套 FastAPI 后端 API**（`http://<host>:8000/api`，JWT 鉴权），三端数据一致（计划 D17）。

## 架构

```
ui/  (Jetpack Compose + Navigation)          network/                     后端
┌─────────────────────────────────┐   ┌──────────────────────┐
│ LoginScreen ── LoginViewModel   │   │ ApiClient (Retrofit  │   HTTP   FastAPI
│ DeviceListScreen ── ListVM      │──►│  + OkHttp + Bearer   │────────► :8000/api
│ DeviceDetailScreen ── DetailVM  │   │  拦截器)              │
│ BatchScreen ── BatchVM          │   │ ApiService (接口契约) │
└─────────────────────────────────┘   │ TokenStore (JWT)     │
  每屏一个 ViewModel                   └──────────────────────┘
  (coroutines + StateFlow)              data/Models.kt (Gson)
```

- **单向数据流**：ViewModel 持有 `StateFlow<UiState>`，Screen `collectAsState()` 渲染；网络在 `viewModelScope` 协程内完成。
- **包名**：`com.cloudphone.app`，所有源码在 `app/src/main/java/com/cloudphone/app/`。

## 页面与后端接口对应

| 页面 | 功能 | 接口 |
|---|---|---|
| LoginScreen | 服务器地址 + 账号密码登录（默认 admin/admin123） | `POST /auth/login` |
| DeviceListScreen | 两列卡片：名称/机型/出口IP/状态 + 缩略图；搜索 | `GET /devices`（5s 轮询）、`GET /devices/{id}/screenshot`（4s 轮询运行中设备） |
| DeviceDetailScreen | 大图投屏（1.5s/帧）+ **点画面直接远程点击**（按分辨率换算坐标）+ 打开网页 / 发送文本 / 返回·主页·回车键 + 一机一码信息 | `GET /devices/{id}`、`/screenshot`、`POST /devices/{id}/control/{tap,open_url,text,key}` |
| BatchScreen | 多选设备（可一键全选运行中）→ 批量打开网页 / 批量回主页，显示成功/失败台数 | `POST /batch/open_url`、`POST /batch/key` |

## 配置后端地址

两种方式（任选其一）：

1. **编译期默认值**：`app/build.gradle.kts` → `buildConfigField("String", "BASE_URL", ...)`。
   默认 `http://10.0.2.2:8000/api/`（安卓模拟器访问宿主机回环）；真机测试改为局域网地址，如 `http://<HOST_LAN_IP>:8000/api/`。
2. **运行时覆盖**：登录页顶部"服务器地址"输入框，随时切换，无需重编。

> demo 后端为 HTTP 明文，Manifest 已开 `usesCleartextTraffic="true"`；生产切 HTTPS 后应移除。

## 构建运行

用 Android Studio（Hedgehog+，JDK 17）直接打开 `app-client/` 即可同步运行；或命令行：

```bash
cd app-client
gradle wrapper          # 首次：生成 gradlew 脚本（仓库不带二进制 wrapper jar）
./gradlew assembleDebug # 产物 app/build/outputs/apk/debug/app-debug.apk
```

技术栈版本：AGP 8.4.2 / Kotlin 1.9.24 / Compose BOM 2024.06 / Retrofit 2.11 / minSdk 26 / targetSdk 34。

## 已实现 vs 生产版差异

| 能力 | demo 实现（本仓库） | 生产版 |
|---|---|---|
| 投屏 | **截图轮询**（列表 4s、详情 1.5s，`/devices/{id}/screenshot` 返回 base64 帧） | scrcpy / minicap 视频流（H.264/WebSocket），30fps 低延迟 |
| 实时推送 | 轮询 REST | 后端已有 `ws://<host>:8000/api/ws`（订阅 device_status/preview/batch_progress），App 侧接 OkHttp WebSocket 即可 |
| Token | 内存 TokenStore，进程重启需重新登录 | DataStore 加密持久化 + 刷新令牌 |
| 操控 | tap / open_url / text / key（swipe 接口已封装，UI 未接手势） | 完整手势映射（滑动跟手、多指）、分组筛选、脚本触发 |
| 分组 | `GET /groups` 已封装在 ApiService | 列表页按分组筛选 UI |

投屏用截图轮询是**有意为之的 demo 取舍**：不引入视频解码依赖、任何网络下都能演示"多端看到同一台云手机画面"的主流程；接口层已按契约留好，替换传输通道不影响 UI 层。

## 把 BASE_URL 指到后端（三端联调）

App 与 Web 端、PC 端复用**同一套 FastAPI 后端**（`/api`，JWT 鉴权）。当前 demo 后端跑在
Lima VM 内的 redroid 模式，已通过 ssh 隧道映射到开发机的 `127.0.0.1:8000`，接管 5 台在线真机。
三端指向同一后端后数据天然一致，完整联调步骤见 [`docs/三端联调.md`](../docs/三端联调.md)。

`BASE_URL` 的取值取决于 **App 运行在哪里、后端相对它在哪里**，务必带上 `/api/` 前缀并以 `/` 结尾
（`ApiClient` 会自动补全末尾 `/`，`ApiService` 里的路径是相对 `baseUrl` 拼接的）：

| App 运行环境 | 后端相对位置 | BASE_URL |
|---|---|---|
| **Android 模拟器**（跑在这台开发机上） | 后端隧道在宿主机 `:8000`；`10.0.2.2` 是模拟器专用别名，指向宿主机回环（模拟器里的 `localhost`/`127.0.0.1` 是模拟器自身，连不到宿主机） | `http://10.0.2.2:8000/api/`（= 编译期默认值） |
| **真机 + 与后端同一局域网** | 直连后端主机的 LAN IP；需后端监听 `0.0.0.0:8000` 且手机与主机同网段 | `http://<host-lan-ip>:8000/api/`（例如 `http://<HOST_LAN_IP>:8000/api/`） |
| **直接在这台开发机上跑**（经隧道口，少见） | 本机回环 `127.0.0.1:8000` 即隧道口 | `http://localhost:8000/api/` |

两种设置途径（任选，运行时输入优先）：

1. **编译期默认**：`app/build.gradle.kts` →
   `buildConfigField("String", "BASE_URL", "\"http://10.0.2.2:8000/api/\"")`，改后需重编。
2. **运行时覆盖**（推荐联调用）：登录页顶部"服务器地址"输入框，登录时 `LoginViewModel` 先调
   `ApiClient.setBaseUrl(...)` 再 `POST /auth/login`，改地址无需重编，`Retrofit` 会按新地址重建。

自检：真机/模拟器所在环境能否访问后端，可先在能到达该网络的机器上执行
`curl -s --noproxy '*' -X POST http://<上表地址去掉/api/>:8000/api/auth/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin123"}'`，
返回 `access_token` 即通。用 `admin/admin123` 登录后 App 应看到与 Web/PC 相同的 5 台真机。

> 代理陷阱：开发机系统代理会劫持 localhost，命令行自检务必加 `--noproxy '*'` 或
> `NO_PROXY=127.0.0.1,localhost`（App 自身走系统网络栈，通常不受影响）。

## 目录

```
app-client/
├── settings.gradle.kts / build.gradle.kts / gradle.properties
├── gradle/wrapper/gradle-wrapper.properties
└── app/
    ├── build.gradle.kts / proguard-rules.pro
    └── src/main/
        ├── AndroidManifest.xml          # INTERNET 权限 + 明文流量（demo）
        ├── res/values/{strings,themes}.xml
        └── java/com/cloudphone/app/
            ├── MainActivity.kt          # NavHost：login → devices → {device/{id}, batch}
            ├── data/Models.kt           # Device/Fingerprint/LoginResp/Batch* 等契约模型
            ├── network/                 # ApiClient / ApiService / TokenStore
            └── ui/
                ├── theme/Theme.kt       # Material3 主题 + 状态色
                ├── common/Components.kt # base64 帧解码、DeviceFrame、StatusChip
                ├── login/  devices/  detail/  batch/   # 每屏 Screen + ViewModel
```
