# 低延迟投屏（scrcpy / ws-scrcpy）

平台内置的多画面/操控预览走**截图轮询**（`GET /devices/{id}/screenshot`，后端 adb `screencap`）：
- 单机操控页已做**高频轮询**，实测 `/screenshot` ~64ms，可到 **~10-12fps**（操控页右上「高清投屏」开关切到 12fps）。
- 优点：零额外依赖、任意浏览器都能看、和 simulator 模式统一。
- 局限：PNG 帧较大、非真视频编码，达不到 30fps 丝滑。

要**真·丝滑 30fps 低延迟视频流**，用 **ws-scrcpy**（scrcpy-server H.264 编码 + 浏览器端 Broadway/MSE/WebCodecs 解码）。

## 部署（在 Redroid 所在的 Linux 宿主 / Lima VM 内）

```bash
bash deploy/scrcpy/setup-ws-scrcpy.sh     # 装 Node20 + 克隆 + npm install + 构建（较重）
bash deploy/scrcpy/run-ws-scrcpy.sh       # 启动，默认 :8100
```

> ⚠️ ws-scrcpy 依赖树较老较大，`npm install`/`webpack` 在受限 VM（内存/CPU 紧）上较慢，建议在**正式 Linux 宿主机**上构建运行。

## 接入（从本机 Mac 访问 VM 里的 ws-scrcpy）

```bash
ssh -F ~/.lima/redroid/ssh.config -L 127.0.0.1:8100:127.0.0.1:8100 -N -f lima-redroid
# 浏览器打开 http://localhost:8100 → 设备列表 → 点设备 → 实时 H.264 投屏
```

平台前端集成：操控页可加「高清投屏(scrcpy)」按钮，`window.open('http://localhost:8100/#!action=stream&udid=localhost:5556&player=broadway')`（udid=该设备的 adb 序列，redroid 为 `localhost:<5555+id>`）。生产建议把 ws-scrcpy 反代到同一域下统一鉴权。

## 已验证（本机 Lima VM 真机）

- **scrcpy CLI 3.3.4 无头录制真机 H.264 成功**：`scrcpy -s localhost:5557 --no-window --no-audio --record rec.mkv --time-limit 3`，ffprobe 确认 `codec=h264 720x1280`，抽帧见 `docs/screenshots/真机_scrcpy_H264帧.png`。→ **redroid 软件 H.264 编码链路可行**。
- **ws-scrcpy（浏览器流）**：依赖树老、`npm install`/webpack 在本 8G VM 上过慢，未在此环境跑通；已交付 `setup/run` 脚本，请在**正式 Linux 宿主机**上构建运行。
- **平台内置高清模式**：操控页「高清投屏 12fps」开关已上线（改 `stores/devices.js` 轮询下限 + `Control.vue`），今天即可用。

## 关于 Redroid 的编码

Redroid 无硬件编码器，scrcpy 走 **Android 软件 H.264 编码器**（`c2.android.avc.encoder`）：能编码、比截图流畅省带宽，但 fps 受软件编码限制；**真高帧率/低延迟需 Intel/AMD 裸机的 VAAPI 硬编**（见 `docs/architecture.md` 硬件选型）。

## 选型建议

| 场景 | 方案 |
|---|---|
| 多画面网格监看 | 截图轮询（~1fps/台，省资源） |
| 单机重点操控 | 操控页「高清投屏」12fps，或 ws-scrcpy |
| 演示级丝滑投屏 | ws-scrcpy + 宿主硬件编码 |
