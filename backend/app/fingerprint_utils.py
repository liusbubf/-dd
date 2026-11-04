"""从 Device.fingerprint（JSON 列）提取一机一码字段的共享工具。

alerts / metrics / reports 三个模块各自独立实现了 _model_of / _exit_ip_of，
这里统一抽到一处，避免重复且口径一致。
"""
from __future__ import annotations

from .models import Device


def model_of(device: Device) -> str:
    """从指纹中取机型；缺失时归入「未知机型」。"""
    fp = device.fingerprint or {}
    model = (fp.get("device") or {}).get("model")
    return model or "未知机型"


def exit_ip_of(device: Device) -> str | None:
    """从指纹中取出口 IP。"""
    fp = device.fingerprint or {}
    return (fp.get("network") or {}).get("exit_ip")


def android_id_of(device: Device) -> str | None:
    """从指纹中取 Android ID。"""
    fp = device.fingerprint or {}
    return (fp.get("device") or {}).get("android_id")


def fingerprint_summary(device: Device) -> dict:
    """返回设备指纹的核心摘要字段（供列表/详情展示）。"""
    return {
        "model": model_of(device),
        "android_id": android_id_of(device),
        "exit_ip": exit_ip_of(device),
    }
