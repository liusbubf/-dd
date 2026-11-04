package com.cloudphone.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.cloudphone.app.network.TokenStore
import com.cloudphone.app.ui.batch.BatchScreen
import com.cloudphone.app.ui.detail.DeviceDetailScreen
import com.cloudphone.app.ui.devices.DeviceListScreen
import com.cloudphone.app.ui.login.LoginScreen
import com.cloudphone.app.ui.theme.CloudPhoneTheme

/** 导航路由常量 */
object Routes {
    const val LOGIN = "login"
    const val DEVICES = "devices"
    const val DEVICE_DETAIL = "device/{deviceId}"
    const val BATCH = "batch"

    fun deviceDetail(deviceId: Int) = "device/$deviceId"
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            CloudPhoneTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    AppNavHost()
                }
            }
        }
    }
}

/**
 * 导航图：登录 → 设备列表 → { 设备详情, 批量操作 }。
 * demo 版 token 存内存，进程重启回登录页。
 */
@Composable
fun AppNavHost() {
    val navController = rememberNavController()
    val startDestination = if (TokenStore.isLoggedIn) Routes.DEVICES else Routes.LOGIN

    NavHost(navController = navController, startDestination = startDestination) {

        composable(Routes.LOGIN) {
            LoginScreen(
                onLoggedIn = {
                    navController.navigate(Routes.DEVICES) {
                        popUpTo(Routes.LOGIN) { inclusive = true }
                    }
                },
            )
        }

        composable(Routes.DEVICES) {
            DeviceListScreen(
                onOpenDevice = { deviceId -> navController.navigate(Routes.deviceDetail(deviceId)) },
                onOpenBatch = { navController.navigate(Routes.BATCH) },
                onLogout = {
                    navController.navigate(Routes.LOGIN) {
                        popUpTo(0) { inclusive = true }
                    }
                },
            )
        }

        composable(
            route = Routes.DEVICE_DETAIL,
            arguments = listOf(navArgument("deviceId") { type = NavType.IntType }),
        ) { backStackEntry ->
            val deviceId = backStackEntry.arguments?.getInt("deviceId") ?: return@composable
            DeviceDetailScreen(
                deviceId = deviceId,
                onBack = { navController.popBackStack() },
            )
        }

        composable(Routes.BATCH) {
            BatchScreen(onBack = { navController.popBackStack() })
        }
    }
}
