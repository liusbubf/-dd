package com.cloudphone.app.ui.detail

import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.cloudphone.app.ui.common.DeviceFrame
import com.cloudphone.app.ui.common.StatusChip

/**
 * 设备详情页：大图投屏（点按直接操控）+ 打开网页 / 发送文本 / 实体键。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DeviceDetailScreen(
    deviceId: Int,
    onBack: () -> Unit,
    viewModel: DeviceDetailViewModel = viewModel(factory = DeviceDetailViewModel.factory(deviceId)),
) {
    val state by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    var urlInput by remember { mutableStateOf("https://") }
    var textInput by remember { mutableStateOf("") }

    DisposableEffect(Unit) {
        viewModel.startPolling()
        onDispose { viewModel.stopPolling() }
    }

    // 操作结果用 Snackbar 提示
    LaunchedEffect(state.message) {
        val msg = state.message ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(msg)
        viewModel.consumeMessage()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = state.device?.name ?: "设备 #$deviceId",
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    state.device?.let { StatusChip(it.status, Modifier.padding(end = 12.dp)) }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { padding ->
        val device = state.device
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
        ) {
            // ---- 投屏画面（点按 = 远程 tap，按显示比例换算真实坐标） ----
            val aspect = if (device != null && device.height > 0) {
                device.width.toFloat() / device.height.toFloat()
            } else 9f / 16f

            DeviceFrame(
                frame = state.frame,
                placeholderText = when {
                    device == null -> "加载中…"
                    !device.isRunning -> "设备未运行"
                    else -> "等待画面…"
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(aspect)
                    .pointerInput(device?.id) {
                        detectTapGestures { offset ->
                            // size 为该投屏区域像素尺寸；换算成 0~1 相对坐标交给 VM
                            if (size.width > 0 && size.height > 0) {
                                viewModel.tap(
                                    xRatio = offset.x / size.width,
                                    yRatio = offset.y / size.height,
                                )
                            }
                        }
                    },
            )
            Text(
                text = "提示：直接点画面即可远程点击（demo 为截图轮询，约 1.5s 一帧）",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.secondary,
                modifier = Modifier.padding(top = 6.dp),
            )

            if (state.error != null) {
                Text(
                    text = state.error ?: "",
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }

            Spacer(Modifier.height(16.dp))

            // ---- 打开网页 ----
            Text("打开网页", style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                OutlinedTextField(
                    value = urlInput,
                    onValueChange = { urlInput = it },
                    singleLine = true,
                    placeholder = { Text("https://example.com") },
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                Button(onClick = { viewModel.openUrl(urlInput) }) {
                    Text("打开")
                }
            }

            Spacer(Modifier.height(16.dp))

            // ---- 发送文本（输给云手机当前焦点输入框） ----
            Text("发送文本", style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                OutlinedTextField(
                    value = textInput,
                    onValueChange = { textInput = it },
                    singleLine = true,
                    placeholder = { Text("输入要发送的文本") },
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                Button(onClick = {
                    viewModel.sendText(textInput)
                    textInput = ""
                }) {
                    Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "发送")
                }
            }

            Spacer(Modifier.height(16.dp))

            // ---- 实体键 ----
            Text("按键", style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { viewModel.sendKey("back") }, modifier = Modifier.weight(1f)) {
                    Text("返回")
                }
                OutlinedButton(onClick = { viewModel.sendKey("home") }, modifier = Modifier.weight(1f)) {
                    Text("主页")
                }
                OutlinedButton(onClick = { viewModel.sendKey("enter") }, modifier = Modifier.weight(1f)) {
                    Text("回车")
                }
            }

            // ---- 设备信息（一机一码摘要） ----
            if (device != null) {
                Spacer(Modifier.height(16.dp))
                Text("设备信息", style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.height(6.dp))
                InfoRow("机型", device.modelText)
                InfoRow("出口 IP", device.exitIpText)
                InfoRow("分辨率", "${device.width}×${device.height} @${device.dpi}dpi")
                InfoRow("当前网页", device.currentUrl ?: "-")
                InfoRow("Android ID", device.fingerprint?.device?.androidId ?: "-")
                InfoRow("MAC", device.fingerprint?.device?.mac ?: "-")
            }
        }
    }
}

@Composable
private fun InfoRow(label: String, value: String) {
    Row(modifier = Modifier.padding(vertical = 2.dp)) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.secondary,
            modifier = Modifier.width(88.dp),
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
