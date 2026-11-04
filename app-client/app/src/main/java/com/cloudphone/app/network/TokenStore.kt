package com.cloudphone.app.network

import com.cloudphone.app.data.UserInfo

/**
 * Token 存储（demo 版：进程内存）。
 *
 * 登录成功后写入，OkHttp 拦截器读取并附加 Bearer 头。
 * 生产版应换成 Jetpack DataStore（加密）并支持 token 刷新；
 * demo 阶段进程被杀后重新登录即可，符合"主流程跑通"范围。
 */
object TokenStore {

    @Volatile
    var token: String? = null
        private set

    @Volatile
    var user: UserInfo? = null
        private set

    val isLoggedIn: Boolean get() = !token.isNullOrBlank()

    fun save(token: String, user: UserInfo) {
        this.token = token
        this.user = user
    }

    /** 退出登录 / 401 时清空 */
    fun clear() {
        token = null
        user = null
    }
}
