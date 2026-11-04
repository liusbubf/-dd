package com.cloudphone.app.ui.devices

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cloudphone.app.data.Device
import com.cloudphone.app.network.ApiClient
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

data class DeviceListUiState(
    val devices: List<Device> = emptyList(),
    /** deviceId -> data URL 帧（列表缩略图，低频轮询） */
    val frames: Map<Int, String> = emptyMap(),
    val query: String = "",
    val loading: Boolean = false,
    val error: String? = null,
)

/**
 * 设备列表：
 * - 每 5s 拉一次 /devices 刷新状态；
 * - 每 4s 逐台拉运行中设备的 /devices/{id}/screenshot 作缩略图（demo 轮询方案）。
 */
class DeviceListViewModel : ViewModel() {

    private val _uiState = MutableStateFlow(DeviceListUiState())
    val uiState: StateFlow<DeviceListUiState> = _uiState.asStateFlow()

    private var listJob: Job? = null
    private var frameJob: Job? = null

    /** 进入页面时启动轮询（对应 Screen 的 LaunchedEffect），离开时 stopPolling */
    fun startPolling() {
        if (listJob?.isActive == true) return

        listJob = viewModelScope.launch {
            while (isActive) {
                refresh()
                delay(LIST_INTERVAL_MS)
            }
        }
        frameJob = viewModelScope.launch {
            while (isActive) {
                pollFramesOnce()
                delay(FRAME_INTERVAL_MS)
            }
        }
    }

    fun stopPolling() {
        listJob?.cancel(); listJob = null
        frameJob?.cancel(); frameJob = null
    }

    fun onQueryChange(value: String) {
        _uiState.update { it.copy(query = value) }
    }

    /** 拉设备列表；query 走后端 q 参数（名称模糊搜索） */
    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true) }
            try {
                val q = _uiState.value.query.trim().ifBlank { null }
                val devices = ApiClient.api.devices(q = q)
                _uiState.update { it.copy(devices = devices, loading = false, error = null) }
            } catch (e: Exception) {
                _uiState.update { it.copy(loading = false, error = "设备列表加载失败：${e.message ?: "网络错误"}") }
            }
        }
    }

    /** 逐台拉运行中设备截图；单台失败不影响其他台 */
    private suspend fun pollFramesOnce() {
        val running = _uiState.value.devices.filter { it.isRunning }
        for (device in running) {
            try {
                val shot = ApiClient.api.screenshot(device.id)
                val frame = shot.frame ?: continue
                _uiState.update { it.copy(frames = it.frames + (device.id to frame)) }
            } catch (_: Exception) {
                // 缩略图失败静默跳过，保持上一帧
            }
        }
    }

    companion object {
        private const val LIST_INTERVAL_MS = 5_000L
        private const val FRAME_INTERVAL_MS = 4_000L
    }
}
