package com.cloudphone.app.data

import com.google.gson.annotations.SerializedName

/**
 * 数据模型 —— 与 FastAPI 后端契约一一对应（backend/app/schemas.py）。
 * 字段命名后端为 snake_case，这里用 @SerializedName 映射为 Kotlin 风格。
 */

// ---------- 认证 ----------

data class LoginRequest(
    val username: String,
    val password: String,
)

data class UserInfo(
    val id: Int,
    val username: String,
    val role: String,
)

/** POST /auth/login 响应 */
data class LoginResp(
    @SerializedName("access_token") val accessToken: String,
    @SerializedName("token_type") val tokenType: String,
    val user: UserInfo,
)

// ---------- 设备与指纹（一机一码） ----------

/** 设备标识指纹：model / android_id / mac 等，每台各不相同 */
data class DeviceIdentity(
    val brand: String? = null,
    val manufacturer: String? = null,
    val model: String? = null,
    @SerializedName("android_id") val androidId: String? = null,
    val serialno: String? = null,
    val imei: String? = null,
    val mac: String? = null,
    @SerializedName("android_version") val androidVersion: String? = null,
)

/** 浏览器指纹：UA / 分辨率 / 时区 / WebGL / Canvas 噪声 */
data class BrowserFingerprint(
    @SerializedName("user_agent") val userAgent: String? = null,
    @SerializedName("chrome_version") val chromeVersion: String? = null,
    val width: Int? = null,
    val height: Int? = null,
    val dpi: Int? = null,
    val timezone: String? = null,
    val language: String? = null,
    @SerializedName("webgl_vendor") val webglVendor: String? = null,
    @SerializedName("webgl_renderer") val webglRenderer: String? = null,
    @SerializedName("canvas_noise_seed") val canvasNoiseSeed: String? = null,
)

/** 网络信息：代理位 + 独立出口 IP */
data class NetworkInfo(
    val proxy: String? = null,
    @SerializedName("exit_ip") val exitIp: String? = null,
)

data class Fingerprint(
    val device: DeviceIdentity? = null,
    val browser: BrowserFingerprint? = null,
    val network: NetworkInfo? = null,
)

/** 设备状态：creating / running / stopped / error */
object DeviceStatus {
    const val CREATING = "creating"
    const val RUNNING = "running"
    const val STOPPED = "stopped"
    const val ERROR = "error"
}

data class Device(
    val id: Int,
    val name: String,
    @SerializedName("group_id") val groupId: Int? = null,
    val status: String,
    @SerializedName("adb_port") val adbPort: Int? = null,
    val width: Int,
    val height: Int,
    val dpi: Int,
    @SerializedName("current_url") val currentUrl: String? = null,
    val fingerprint: Fingerprint? = null,
    @SerializedName("created_at") val createdAt: String? = null,
    @SerializedName("updated_at") val updatedAt: String? = null,
) {
    val isRunning: Boolean get() = status == DeviceStatus.RUNNING

    /** 列表卡片展示用：机型 */
    val modelText: String get() = fingerprint?.device?.model ?: "-"

    /** 列表卡片展示用：出口 IP */
    val exitIpText: String get() = fingerprint?.network?.exitIp ?: "-"
}

data class Group(
    val id: Int,
    val name: String,
    @SerializedName("parent_id") val parentId: Int? = null,
    @SerializedName("created_at") val createdAt: String? = null,
)

/** GET /devices/{id}/screenshot 响应；frame 为 data:image/... base64 图片 */
data class ScreenshotResp(
    @SerializedName("device_id") val deviceId: Int,
    val frame: String? = null,
)

// ---------- 单机操控 ----------

data class TapReq(val x: Int, val y: Int)

data class SwipeReq(
    val x1: Int,
    val y1: Int,
    val x2: Int,
    val y2: Int,
    @SerializedName("duration_ms") val durationMs: Int = 300,
)

data class TextReq(val text: String)

/** key: back / home / menu / power / volume_up / volume_down / enter */
data class KeyReq(val key: String)

data class OpenUrlReq(val url: String)

// ---------- 批量操作 ----------

data class BatchOpenUrlReq(
    @SerializedName("device_ids") val deviceIds: List<Int>,
    val url: String,
)

data class BatchKeyReq(
    @SerializedName("device_ids") val deviceIds: List<Int>,
    val key: String,
)

data class BatchResult(
    val total: Int,
    val ok: Int,
    val failed: Int,
)
