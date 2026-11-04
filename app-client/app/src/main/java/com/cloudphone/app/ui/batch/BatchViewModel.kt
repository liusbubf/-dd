package com.cloudphone.app.ui.batch

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cloudphone.app.data.BatchKeyReq
import com.cloudphone.app.data.BatchOpenUrlReq
import com.cloudphone.app.data.Device
import com.cloudphone.app.network.ApiClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class BatchUiState(
    val devices: List<Device> = emptyList(),
    val selected: Set<Int> = emptySet(),
    val url: String = "https://",
    val loading: Boolean = false,
    val submitting: Boolean = false,
    val error: String? = null,
    /** 批量结果提示，如"批量打开网页：成功 8/10" */
    val message: String? = null,
)

/**
 * 批量操作（计划 D15）：多选设备 → 一键批量打开网页（POST /batch/open_url）。
 * 附带批量返回主页（/batch/key）作为演示第二动作。
 */
class BatchViewModel : ViewModel() {

    private val _uiState = MutableStateFlow(BatchUiState())
    val uiState: StateFlow<BatchUiState> = _uiState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true) }
            try {
                val devices = ApiClient.api.devices()
                _uiState.update { state ->
                    state.copy(
                        devices = devices,
                        // 剔除已不存在的选中项
                        selected = state.selected intersect devices.map { it.id }.toSet(),
                        loading = false,
                        error = null,
                    )
                }
            } catch (e: Exception) {
                _uiState.update { it.copy(loading = false, error = "设备列表加载失败：${e.message ?: "网络错误"}") }
            }
        }
    }

    fun onUrlChange(value: String) = _uiState.update { it.copy(url = value) }

    fun toggle(deviceId: Int) = _uiState.update { state ->
        val selected = if (deviceId in state.selected) state.selected - deviceId else state.selected + deviceId
        state.copy(selected = selected)
    }

    /** 全选运行中的设备 / 取消全选 */
    fun toggleSelectAllRunning() = _uiState.update { state ->
        val runningIds = state.devices.filter { it.isRunning }.map { it.id }.toSet()
        val selected = if (state.selected.containsAll(runningIds) && runningIds.isNotEmpty()) emptySet() else runningIds
        state.copy(selected = selected)
    }

    /** 一键让选中的所有设备打开同一网页 */
    fun batchOpenUrl() {
        val state = _uiState.value
        val ids = state.selected.toList()
        val url = state.url.trim()
        when {
            ids.isEmpty() -> _uiState.update { it.copy(message = "请先勾选设备") }
            url.isBlank() -> _uiState.update { it.copy(message = "请输入网址") }
            else -> submit("批量打开网页") { ApiClient.api.batchOpenUrl(BatchOpenUrlReq(ids, url)) }
        }
    }

    /** 批量回到 iOS 皮肤主屏（key = home） */
    fun batchHome() {
        val ids = _uiState.value.selected.toList()
        if (ids.isEmpty()) {
            _uiState.update { it.copy(message = "请先勾选设备") }
            return
        }
        submit("批量回主页") { ApiClient.api.batchKey(BatchKeyReq(ids, "home")) }
    }

    fun consumeMessage() = _uiState.update { it.copy(message = null) }

    private fun submit(label: String, block: suspend () -> com.cloudphone.app.data.BatchResult) {
        viewModelScope.launch {
            _uiState.update { it.copy(submitting = true) }
            try {
                val result = block()
                _uiState.update {
                    it.copy(submitting = false, message = "$label：成功 ${result.ok}/${result.total}，失败 ${result.failed}")
                }
            } catch (e: Exception) {
                _uiState.update { it.copy(submitting = false, message = "$label 失败：${e.message ?: "网络错误"}") }
            }
        }
    }
}
