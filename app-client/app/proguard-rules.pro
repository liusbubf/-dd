# demo 阶段不开启混淆（isMinifyEnabled = false）。
# 若后续开启，需保留 Gson 反射用到的数据模型：
-keep class com.cloudphone.app.data.** { *; }
-keepattributes Signature
-keepattributes *Annotation*
