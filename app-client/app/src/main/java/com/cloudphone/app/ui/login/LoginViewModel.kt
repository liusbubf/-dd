package com.cloudphone.app.ui.login

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cloudphone.app.data.LoginRequest
import com.cloudphone.app.network.ApiClient
import com.cloudphone.app.network.TokenStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class LoginUiState(
    val serverUrl: String = ApiClient.baseUrl,
    val username: String = "admin",
    val password: String = "",
    val loading: Boolean = false,
    val error: String? = null,
)

class LoginViewModel : ViewModel() {

    private val _uiState = MutableStateFlow(LoginUiState())
    val uiState: StateFlow<LoginUiState> = _uiState.asStateFlow()

    fun onServerUrlChange(value: String) = _uiState.update { it.copy(serverUrl = value, error = null) }
    fun onUsernameChange(value: String) = _uiState.update { it.copy(username = value, error = null) }
    fun onPasswordChange(value: String) = _uiState.update { it.copy(password = value, error = null) }

    /** 登录：先切基地址，再 POST /auth/login，成功后保存 JWT */
    fun login(onSuccess: () -> Unit) {
        val state = _uiState.value
        if (state.username.isBlank() || state.password.isBlank()) {
            _uiState.update { it.copy(error = "请输入用户名和密码") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, error = null) }
            try {
                ApiClient.setBaseUrl(state.serverUrl)
                val resp = ApiClient.api.login(LoginRequest(state.username.trim(), state.password))
                TokenStore.save(resp.accessToken, resp.user)
                _uiState.update { it.copy(loading = false) }
                onSuccess()
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(loading = false, error = "登录失败：${e.message ?: "网络错误"}")
                }
            }
        }
    }
}
