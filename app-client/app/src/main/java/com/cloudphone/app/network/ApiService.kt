package com.cloudphone.app.network

import com.cloudphone.app.data.BatchKeyReq
import com.cloudphone.app.data.BatchOpenUrlReq
import com.cloudphone.app.data.BatchResult
import com.cloudphone.app.data.Device
import com.cloudphone.app.data.Group
import com.cloudphone.app.data.KeyReq
import com.cloudphone.app.data.LoginRequest
import com.cloudphone.app.data.LoginResp
import com.cloudphone.app.data.OpenUrlReq
import com.cloudphone.app.data.ScreenshotResp
import com.cloudphone.app.data.SwipeReq
import com.cloudphone.app.data.TapReq
import com.cloudphone.app.data.TextReq
import com.cloudphone.app.data.UserInfo
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * 后端 API 契约（base = http://<host>:8000/api/），与 Web / PC 端共用同一后端。
 */
interface ApiService {

    // ---------- 认证 ----------

    @POST("auth/login")
    suspend fun login(@Body body: LoginRequest): LoginResp

    @GET("auth/me")
    suspend fun me(): UserInfo

    // ---------- 设备 ----------

    @GET("devices")
    suspend fun devices(
        @Query("group_id") groupId: Int? = null,
        @Query("status") status: String? = null,
        @Query("q") q: String? = null,
    ): List<Device>

    @GET("devices/{id}")
    suspend fun device(@Path("id") id: Int): Device

    /** 投屏预览（demo 用轮询截图；生产换 scrcpy/minicap 视频流） */
    @GET("devices/{id}/screenshot")
    suspend fun screenshot(@Path("id") id: Int): ScreenshotResp

    @POST("devices/{id}/start")
    suspend fun start(@Path("id") id: Int): Device

    @POST("devices/{id}/stop")
    suspend fun stop(@Path("id") id: Int): Device

    @POST("devices/{id}/restart")
    suspend fun restart(@Path("id") id: Int): Device

    // ---------- 分组 ----------

    @GET("groups")
    suspend fun groups(): List<Group>

    // ---------- 单机操控 ----------

    @POST("devices/{id}/control/open_url")
    suspend fun openUrl(@Path("id") id: Int, @Body body: OpenUrlReq)

    @POST("devices/{id}/control/tap")
    suspend fun tap(@Path("id") id: Int, @Body body: TapReq)

    @POST("devices/{id}/control/swipe")
    suspend fun swipe(@Path("id") id: Int, @Body body: SwipeReq)

    @POST("devices/{id}/control/text")
    suspend fun text(@Path("id") id: Int, @Body body: TextReq)

    @POST("devices/{id}/control/key")
    suspend fun key(@Path("id") id: Int, @Body body: KeyReq)

    // ---------- 批量操作 ----------

    @POST("batch/open_url")
    suspend fun batchOpenUrl(@Body body: BatchOpenUrlReq): BatchResult

    @POST("batch/key")
    suspend fun batchKey(@Body body: BatchKeyReq): BatchResult
}
