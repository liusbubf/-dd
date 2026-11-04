// X86 云手机平台 · 安卓客户端（Kotlin + Jetpack Compose）
// 作者：顺天 ｜ 许可：MIT（见仓库根 LICENSE / AUTHORS）

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.cloudphone.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.cloudphone.app"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"       // 作者：顺天（AndroidManifest 侧由仓库根 AUTHORS/NOTICE 统一署名）

        // 后端基地址（默认取安卓模拟器访问宿主机的 10.0.2.2；真机改为局域网 IP）。
        // 登录页也提供"服务器地址"输入框，可在运行时覆盖此值。
        buildConfigField("String", "BASE_URL", "\"http://10.0.2.2:8000/api/\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    composeOptions {
        // 与 Kotlin 1.9.24 匹配的 Compose 编译器版本
        kotlinCompilerExtensionVersion = "1.5.14"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.06.00")
    implementation(composeBom)

    // AndroidX 基础
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.3")

    // Compose UI + Material3
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    debugImplementation("androidx.compose.ui:ui-tooling")

    // 导航
    implementation("androidx.navigation:navigation-compose:2.7.7")

    // 网络：Retrofit + OkHttp + Gson（对接 FastAPI 后端 /api）
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-gson:2.11.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

    // 协程
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
}
