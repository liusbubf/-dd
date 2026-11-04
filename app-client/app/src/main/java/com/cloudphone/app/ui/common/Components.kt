package com.cloudphone.app.ui.common

import android.graphics.BitmapFactory
import android.util.Base64
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import com.cloudphone.app.data.DeviceStatus
import com.cloudphone.app.ui.theme.StatusColors

/**
 * 把后端返回的 frame（data:image/png;base64,xxx 形式的 data URL）解码为 ImageBitmap。
 * 解码失败返回 null（上层显示占位）。
 */
fun decodeFrame(frame: String?): ImageBitmap? {
    if (frame.isNullOrBlank()) return null
    return try {
        // 兼容纯 base64 与 data URL 两种形式
        val b64 = frame.substringAfter("base64,", frame)
        val bytes = Base64.decode(b64, Base64.DEFAULT)
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
    } catch (_: Exception) {
        null
    }
}

/**
 * 设备画面预览：有帧则显示截图，无帧显示深色占位。
 * demo 采用截图轮询（生产版换 scrcpy/minicap 视频流，见 README）。
 */
@Composable
fun DeviceFrame(
    frame: String?,
    modifier: Modifier = Modifier,
    placeholderText: String = "暂无画面",
) {
    val bitmap = remember(frame) { decodeFrame(frame) }
    if (bitmap != null) {
        Image(
            bitmap = bitmap,
            contentDescription = "设备画面",
            modifier = modifier,
            contentScale = ContentScale.Fit,
        )
    } else {
        Box(
            modifier = modifier.background(Color(0xFF111827)),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = placeholderText,
                color = Color(0xFF6B7280),
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

/** 设备状态 -> 中文标签 */
fun statusLabel(status: String): String = when (status) {
    DeviceStatus.RUNNING -> "运行中"
    DeviceStatus.STOPPED -> "已停止"
    DeviceStatus.CREATING -> "创建中"
    DeviceStatus.ERROR -> "异常"
    else -> status
}

/** 设备状态 -> 颜色 */
fun statusColor(status: String): Color = when (status) {
    DeviceStatus.RUNNING -> StatusColors.Running
    DeviceStatus.STOPPED -> StatusColors.Stopped
    DeviceStatus.CREATING -> StatusColors.Creating
    DeviceStatus.ERROR -> StatusColors.Error
    else -> StatusColors.Stopped
}

/** 状态小圆点 + 文本标签 */
@Composable
fun StatusChip(status: String, modifier: Modifier = Modifier) {
    val color = statusColor(status)
    Box(
        modifier = modifier
            .background(color.copy(alpha = 0.12f), RoundedCornerShape(999.dp)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = statusLabel(status),
            color = color,
            style = MaterialTheme.typography.labelSmall,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
        )
    }
}
