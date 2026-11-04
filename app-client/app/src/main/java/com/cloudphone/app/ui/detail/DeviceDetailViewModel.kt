package com.cloudphone.app.ui.detail

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.cloudphone.app.data.Device
import com.cloudphone.app.data.KeyReq
import com.cloudphone.app.data.OpenUrlReq
import com.cloudphone.app.data.TapReq
import com.cloudphone.app.data.TextReq
import com.cloudphone.app.network.ApiClient
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

data class DeviceDetailUiState(
    val device: Device? = null,
    /** 大图预览帧（高频轮询） */
    val frame: String? = null,
    val loading: Boolean = true,
    val error: String? = null,
    /** 操作结果提示（如"已下发打开网页"），一次性消费 */
    val message: String? = null,
)

/**
 * 设备详情（计划 D14–D15 基础操控）：
 * - 1.5s 轮询截图作"准实时"投屏（demo 方案，生产换 scrcpy 流）；
 * - 点画面 → 按比例换算成设备真实坐标 → POST control/tap；
 * - 打开网页 / 发送文本 / 实体键（返回、主页、回车）。
 */
class DeviceDetailViewModel(private val deviceId: Int) : ViewModel() {

    private val _uiState = MutableStateFlow(DeviceDetailUiState())
    val uiState: StateFlow<DeviceDetailUiState> = _uiState.asStateFlow()

    private var pollJob: Job? = null

    fun startPolling() {
        if (pollJob?.isActive == true) return
        pollJob = viewModelScope.launch {
            var tick = 0
            while (isActive) {
                // 每 4 个截图周期（约 6s）顺带刷新一次设备信息
                if (tick % 4 == 0) refreshDevice()
                pollFrame()
                tick++
                delay(FRAME_INTERVAL_MS)
            }
        }
    }

    fun stopPolling() {
        pollJob?.cancel()
        pollJob = null
    }

    private suspend fun refreshDevice() {
        try {
            val device = ApiClient.api.device(deviceId)
            _uiState.update { it.copy(device = device, loading = false, error = null) }
        } catch (e: Exception) {
            _uiState.update { it.copy(loading = false, error = "设备信息获取失败：${e.message ?: "网络错误"}") }
        }
    }

    private suspend fun pollFrame() {
        val device = _uiState.value.device ?: return
        if (!device.isRunning) return
        try {
            val shot = ApiClient.api.screenshot(deviceId)
            if (shot.frame != null) {
                _uiState.update { it.copy(frame = shot.frame) }
            }
        } catch (_: Exception) {
            // 保持上一帧
        }
    }

    /**
     * 点击投屏画面：xRatio / yRatio 为画面内相对坐标（0~1），
     * 换算成云手机真实分辨率坐标后下发 tap。
     */
    fun tap(xRatio: Float, yRatio: Float) {
        val device = _uiState.value.device ?: return
        val x = (xRatio * device.width).roundToInt().coerceIn(0, device.width - 1)
        val y = (yRatio * device.height).roundToInt().coerceIn(0, device.height - 1)
        launchControl("点击 ($x, $y)") { ApiClient.api.tap(deviceId, TapReq(x, y)) }
    }

    fun openUrl(url: String) {
        val target = url.trim()
        if (target.isBlank()) {
            _uiState.update { it.copy(message = "请输入网址") }
            return
        }
        launchControl("打开网页") { ApiClient.api.openUrl(deviceId, OpenUrlReq(target)) }
    }

    fun sendText(text: String) {
        if (text.isBlank()) return
        launchControl("发送文本") { ApiClient.api.text(deviceId, TextReq(text)) }
    }

    /** key: back / home / menu / enter 等 */
    fun sendKey(key: String) {
        launchControl("按键 $key") { ApiClient.api.key(deviceId, KeyReq(key)) }
    }

    fun consumeMessage() = _uiState.update { it.copy(message = null) }

    private fun launchControl(label: String, block: suspend () -> Unit) {
        viewModelScope.launch {
            try {
                block()
                _uiState.update { it.copy(message = "已下发：$label") }
            } catch (e: Exception) {
                _uiState.update { it.copy(message = "下发失败（$label）：${e.message ?: "网络错误"}") }
            }
        }
    }

    companion object {
        private const val FRAME_INTERVAL_MS = 1_500L

        /** 详情页 ViewModel 需要 deviceId 入参，用 factory 构造 */
        fun factory(deviceId: Int): ViewModelProvider.Factory = viewModelFactory {
            initializer { DeviceDetailViewModel(deviceId) }
        }
    }
}
