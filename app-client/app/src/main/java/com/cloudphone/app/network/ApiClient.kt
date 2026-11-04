package com.cloudphone.app.network

import com.cloudphone.app.BuildConfig
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Retrofit / OkHttp 单例。
 *
 * - 基地址默认取 BuildConfig.BASE_URL（模拟器 10.0.2.2 → 宿主机 8000），
 *   登录页可在运行时通过 [setBaseUrl] 覆盖（真机连局域网后端）。
 * - Bearer 拦截器自动附加 TokenStore 中的 JWT。
 */
object ApiClient {

    @Volatile
    var baseUrl: String = BuildConfig.BASE_URL
        private set

    @Volatile
    private var service: ApiService? = null

    /** JWT Bearer 拦截器：登录接口无 token 时原样放行 */
    private val authInterceptor = Interceptor { chain ->
        val token = TokenStore.token
        val request = if (token.isNullOrBlank()) {
            chain.request()
        } else {
            chain.request().newBuilder()
                .header("Authorization", "Bearer $token")
                .build()
        }
        chain.proceed(request)
    }

    private val okHttpClient: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .addInterceptor(authInterceptor)
            .addInterceptor(HttpLoggingInterceptor().apply {
                // demo 联调打印请求行；截图接口 body 很大，不开 BODY 级别
                level = HttpLoggingInterceptor.Level.BASIC
            })
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .build()
    }

    /**
     * 运行时切换后端地址（登录页"服务器地址"输入框）。
     * 自动补全末尾 "/"，并在变更时重建 Retrofit。
     */
    fun setBaseUrl(url: String) {
        val trimmed = url.trim()
        if (trimmed.isBlank()) return
        val normalized = if (trimmed.endsWith("/")) trimmed else "$trimmed/"
        if (normalized == baseUrl) return
        synchronized(this) {
            baseUrl = normalized
            service = null // 下次访问时按新地址重建
        }
    }

    val api: ApiService
        get() = service ?: synchronized(this) {
            service ?: buildService().also { service = it }
        }

    private fun buildService(): ApiService =
        Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(okHttpClient)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(ApiService::class.java)
}
