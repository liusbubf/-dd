# iOS 皮肤（皮肤级）应用指南 —— 已在真机跑通

> 目标：让浏览器云手机的桌面「看起来像 iPhone」。本月做**皮肤级**（启动器主题 + iOS 壁纸 +
> 圆角图标 + Dock/网格），系统级 ROM 复刻往后放。
>
> 本目录不再是纯占位文档：`apply-ios-skin.sh` + 两个 python 脚本已在 **device1
> (Redroid Android 12 / arm64)** 实测跑通。成品截图见
> `docs/screenshots/真机_iOS皮肤.png`。
>
> **⚡ 本流程已 API 化并升级为「设计稿 1:1」**：平台「一键换肤」接口
> （`backend/app/orchestrator/redroid.py` `apply_skin()`）完整落地 —— 装 Lawnchair
> 1.2.0.1884 → set-home → **设计稿桌面**（`gen-design-icons.py` 从 `preview.py` 同源渲染
> 的 20 个图标 PNG 以 favorites `itemType=1` + icon BLOB 写入，中文标题，布局表
> `orchestrator/ios_layout.py`）→ 分档主题壁纸（`gen-theme-wallpapers.py`，Dock 毛玻璃
> 底板/页面圆点画进壁纸，rid 随设备 seed 轮换）→ 容器重启 → 合并偏好（squircle/网格
> /隐藏日期 widget/Dock 透明/隐藏箭头），并经 WS 实时上报进度（`docs/扩展功能.md` §11）。
> APK 不入 git（`*.apk` ignore）：克隆后先跑 `./fetch-lawnchair.sh`；缺 APK 降级仅壁纸。
> 图标/壁纸资产生成需 macOS + Chrome（无头渲染）+ pillow，产物已入库无需重跑。
> 本脚本保留作为手工调试/单机排障入口。

---

## 0. 实测环境（很重要，脚本按此写）

- 5 台 Redroid 容器跑在 lima VM「redroid」里，容器名 `redroid_1..5`；
  adb 在 VM 内，**设备端口 = 5555 + 序号**（device1 = `localhost:5556`）。
- **adb shell 非 root**（uid=2000）；需要 root 的步骤走 `sudo docker exec redroid_N …`
  （容器内是 root）。
- 容器 `/data` 是**持久 bind mount**（`/root/redroid-data/instN`）→ `docker restart` **不丢数据**，
  所以「写壁纸文件 + 重启实例」这条路可行。
- **SELinux = Disabled**（permissive）→ 直接写 `/data` 下的文件不需要 `restorecon`。
- device1 已装 **Lawnchair V1 `ch.deletescape.lawnchair` 1.2.0.1884** 并设为默认 HOME。

---

## 1. 四件套现状（开源、无 Apple 私有资源）

| 组成 | 状态 | 做法 |
|---|---|---|
| **iOS 壁纸** | ✅ 已跑通 | `gen-wallpaper.py` 生成蓝紫粉渐变 PNG → 写进系统壁纸文件 → 重启加载 |
| **圆角(squircle) 蒙版** | ✅ 已跑通 | 写 Lawnchair 偏好 `pref_override_icon_shape` = 超椭圆 path；自适应图标被裁成 iOS 圆角方形 |
| **4 列网格 + Dock** | ✅ 已跑通 | 写 `pref_numCols/numRows/numHotseatIcons` + 重排 `launcher.db` |
| **默认启动器** | ✅ 已就位 | Lawnchair + `cmd package set-home-activity` |
| **iOS 图标包(字形美术)** | ⏸ 手动/后补 | 见 §4：暂无「授权明确的开源 iOS 字形图标包」，先用圆角蒙版顶上 |

### ⚠️ 字体合规红线（务必遵守）
**禁止**内置或分发 Apple **San Francisco（SF Pro / SF）** —— Apple 知识产权，未授权分发有法律风险。
统一用 **SF 观感的开放字体**替代：**HarmonyOS Sans**（免费商用）/ **思源黑体 Source Han Sans**（OFL）
/ **Inter**（OFL）。圆角用 **squircle 超椭圆**，不使用 Apple 原生图标资源。

---

## 2. 一键套皮

```bash
cd deploy/ios-skin
./apply-ios-skin.sh 1                    # 对 device1 套皮（壁纸+圆角+网格+Dock）
# ./apply-ios-skin.sh 1 /path/lawnchair.apk   # 顺带安装/更新启动器
```

脚本按 lima+docker 环境写死了默认命令；换环境用环境变量覆盖 `ADB / ROOT / DKR / VMSH / SERIAL / CONTAINER`。
脚本会在最后 `docker restart` 该实例并等开机，**只动 device1，不影响其它机**。

---

## 3. 三件事的确切做法（脚本里就是这么干的）

### 3.1 iOS 壁纸（AOSP 没有 `adb set-wallpaper` CLI）
试过三条路，**可行的是「写系统壁纸文件 + 重启实例」**：
- ❌ `cmd wallpaper`：本镜像 `No shell command implementation`，不能设图。
- ❌ 各种 `am`/Intent：需要 UI 手点，不可脚本化。
- ✅ **写文件**：
  ```bash
  # 把 720x1280 PNG 直接写成系统壁纸(裁剪图+原图)，属主 system(1000)，权限 600
  sudo docker cp ios-wallpaper.png redroid_1:/data/system/users/0/wallpaper
  sudo docker exec redroid_1 sh -c '
    cp /data/system/users/0/wallpaper /data/system/users/0/wallpaper_orig
    chown 1000:1000 /data/system/users/0/wallpaper*; chmod 600 /data/system/users/0/wallpaper*'
  sudo docker restart redroid_1     # WallpaperManagerService 开机从盘重载（/data 持久，不丢）
  ```
  `wallpaper_info.xml` 是 Android 12 的 ABX 二进制，无需改；默认 ImageWallpaper 会读上面的
  `wallpaper` 文件。壁纸恰好 720x1280 = 屏幕分辨率，全屏铺满。

壁纸生成（Mac 上无 PIL/imagemagick 也能跑，纯标准库）：
```bash
python3 gen-wallpaper.py ios-wallpaper.png   # 蓝→紫→粉 对角渐变 + 左上柔光
```

### 3.2 圆角(squircle) + 网格 + Dock：改 Lawnchair 偏好
Lawnchair V1 偏好在 `/data/data/ch.deletescape.lawnchair/shared_prefs/*_preferences.xml`（**普通 XML**，
非 ABX）。**本版实测有效的 key（都是 String 型，写成 int 会 ClassCastException 崩启动器）**：

| key | 值 | 作用 |
|---|---|---|
| `pref_numCols` | `4` | 主屏列数（iOS 4 列） |
| `pref_numRows` | `6` | 主屏行数 |
| `pref_numHotseatIcons` | `4` | Dock 图标数 |
| `pref_override_icon_shape` | `M50,0 C10,0 0,10 0,50 0,90 10,100 50,100 90,100 100,90 100,50 100,10 90,0 50,0 Z` | squircle 超椭圆蒙版（Launcher3 IconShapeOverride 标准 path） |

> `pref_pixelStyleIcons` 默认已 true；`backportAdaptiveIcons` 在 Nougat+ 恒为 true（非偏好，代码写死），
> 所以非自适应图标也会被包成自适应再套蒙版。**注意 Android 12 系统默认蒙版本身就是圆角方形**，
> 所以即便 override 不生效，图标也是 iOS 圆角轮廓；override 只是把形状钉死成 squircle。
>
> **⚠️ 写法有坑（都踩过，脚本已修正）**：
> 1. **必须合并、不能整体覆盖**：Lawnchair 开机会跑一次偏好「迁移」，把**整体覆盖写入的 XML 重置掉**
>    （只保留它自己的运行时 key）。正确做法是往它**已生成的** XML 里、`</map>` 前**插入**这几个 key
>    （幂等：先删旧同名 key 再插）。
> 2. **要在壁纸重启之后再写**：因为迁移发生在开机时；顺序应是「改 db + 铺壁纸 → 重启实例 → 开机后再
>    合并偏好 → 只重启启动器」，key 才留得住（脚本就是这个顺序）。
> 3. 改完 `am force-stop` 启动器、属主回填为应用 uid、再 `am start HOME`。

### 3.3 桌面网格：重排 `launcher.db`
新装的 Lawnchair 主屏只有零星几个图标；要铺成 iOS 网格得改 `favorites` 表
（Launcher3 结构：`container` -100=主屏 / -101=Dock；主屏 `cellY=0` 那行被 QSB/日期条占用，**App 从
`cellY=1` 起排**；Dock 用 `screen` 当槽位）。容器内 `sqlite3` 会 abort，所以走 VM 的 python3：
```bash
sudo docker cp redroid_1:/data/data/ch.deletescape.lawnchair/databases/launcher.db /tmp/launcher.db
# apps.tsv 每行:  标题<TAB>package/.Activity（adb query-activities 拿到的启动组件）
python3 populate-grid.py /tmp/launcher.db < apps.tsv
sudo docker cp /tmp/launcher.db redroid_1:/data/data/ch.deletescape.lawnchair/databases/launcher.db
# 属主回填 + 重启启动器
```
`apply-ios-skin.sh` 已把「查应用组件 → 生成 tsv → 改 db → 回填」串好，无需手动。

---

## 4. iOS 图标包（字形美术）—— 目前手动/后补，原因写清楚

想要「每个 App 换成 iOS 那套字形图标」需要一个 **iOS 风格图标包 APK**，Lawnchair 里设
`pref_iconPackPackage=<图标包包名>` 即生效。但：

- **F-Droid / IzzyOnDroid**：主流开源图标包是 **Lawnicons**（Material 线性描边）、Arcticons 等，
  **没有** iOS 字形风格的；`Global Icon Pack` 只是「应用图标包的引擎」，本身不含 iOS 美术。
- **Play 商店的 iOS 图标包**（如 Squircle / Delta 等）多为**闭源、授权不明**，且很多直接照搬
  Apple 图标 —— 与本项目「禁用 Apple 私有资源」红线冲突，**不打包分发**。

**结论**：图标包这一层暂不自动装。现状用 **squircle 圆角蒙版**把系统/三方图标统一成 iOS 圆角方形轮廓
（§3.2 已做），观感已接近 iPhone；若后续要上「iOS 字形」，请：
1. 自建一套开源图标包（squircle 底 + 自绘/开放授权字形），或
2. 采购一份**授权明确**的图标包 APK；装好后：
   ```bash
   adb -s localhost:5556 install -r ios-iconpack.apk
   # 在偏好里加： <string name="pref_iconPackPackage">图标包包名</string>  然后重启启动器
   ```

---

## 5. 与平台联动

- **批量套皮**：对多台实例循环 `./apply-ios-skin.sh N`，即可让「一键创建 N 台」的机器统一 iOS 皮肤
  （验收清单第 2 条「建机后画面显示 iOS 皮肤」）。注意每台会各自 `docker restart`，别并发太多以免 VM 内存吃紧。
- **一机一码正交**：皮肤只改观感；设备标识/指纹仍由 `fingerprint.py` + props 注入决定，互不影响。

## 6. 本目录文件

```
apply-ios-skin.sh   # 一键：默认HOME + 偏好(网格/Dock/圆角) + 重排db + 壁纸 + 重启核验
gen-wallpaper.py    # 生成 720x1280 iOS 渐变壁纸（纯标准库，无需 PIL/imagemagick）
populate-grid.py    # 把应用重排进 launcher.db 的 4 列网格 + Dock
ios-wallpaper.png   # 生成好的壁纸（720x1280）
README.md           # 本文
```

> 系统级 iOS 复刻（SystemUI/控制中心/锁屏/换系统字体）需 ROM/Magisk，属后续路线图，不在本月范围。
