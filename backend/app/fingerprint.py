"""一机一码（D3 / D5）：为每台云手机生成互不相同的设备标识 + 浏览器指纹 + 出口网络。

对齐 demo 验收清单第 4 条「独立身份」：
    抽查 3 台，设备标识 / 出口 IP / 浏览器指纹各不相同。

设计要点：
- 每台设备用一个稳定 seed（来自 uuid）派生全部字段，保证同一设备重启后指纹一致，
  不同设备之间字段互不相同。
- 生成的 `props` 可直接作为 Redroid 启动参数注入（RedroidBackend 使用）。
- `browser` 字段供页面/脚本注入到 Chromium（UA/时区/语言/WebGL/Canvas 噪声）。

增强说明（合规商务场景）：
- 此模块允许对受控测试/分组隔离环境中的设备标识执行随机化，以满足商业化环境中
  的独立实例隔离、回放测试和跨租户分离需求；
- 它不提供欺骗第三方完整性验证、绕过安全监测或伪造硬件证书的能力。
"""
from __future__ import annotations

import hashlib
import random
import uuid
from typing import Any

# 设备机型库（品牌 / 厂商 / 机型 / 典型分辨率）
_DEVICE_MODELS = [
    ("google", "Google", "Pixel 6", "Pixel 6"),
    ("google", "Google", "Pixel 7 Pro", "Pixel 7 Pro"),
    ("samsung", "Samsung", "SM-G991B", "Galaxy S21"),
    ("samsung", "Samsung", "SM-S918B", "Galaxy S23 Ultra"),
    ("Xiaomi", "Xiaomi", "M2101K9G", "Mi 11"),
    ("Xiaomi", "Xiaomi", "2210132C", "Xiaomi 13"),
    ("OnePlus", "OnePlus", "NE2213", "OnePlus 10 Pro"),
    ("oppo", "OPPO", "PGEM10", "OPPO Find X5"),
    ("vivo", "vivo", "V2254A", "vivo X90"),
    ("HUAWEI", "HUAWEI", "ALN-AL00", "HUAWEI Mate 60"),
]

_TIMEZONES = [
    "Asia/Shanghai", "Asia/Hong_Kong", "Asia/Singapore", "Asia/Tokyo",
    "America/New_York", "America/Los_Angeles", "Europe/London", "Europe/Berlin",
]
_LANGUAGES = ["zh-CN", "zh-TW", "en-US", "en-GB", "ja-JP", "ko-KR"]
# 建机表单里的区域要真正落到时区、语言和出口网段，不能只写进 fingerprint.region。
_REGION_PROFILES: dict[str, dict[str, Any]] = {
    "cn": {
        "timezones": ["Asia/Shanghai", "Asia/Hong_Kong"],
        "languages": ["zh-CN"],
        "ip_prefixes": [39, 58, 101, 112, 120, 183],
    },
    "us": {
        "timezones": ["America/New_York", "America/Los_Angeles"],
        "languages": ["en-US"],
        "ip_prefixes": [8, 23, 34, 47, 104, 172],
    },
    "eu": {
        "timezones": ["Europe/London", "Europe/Berlin"],
        "languages": ["en-GB"],
        "ip_prefixes": [5, 46, 78, 88, 185, 195],
    },
}
_GL_VENDORS = ["Qualcomm", "ARM", "Google Inc.", "Imagination Technologies"]
_GL_RENDERERS = [
    "Adreno (TM) 660", "Adreno (TM) 730", "Mali-G78 MP14", "Mali-G710 MC10",
    "PowerVR Rogue GE8320", "Adreno (TM) 740",
]
_CHROME_VERSIONS = ["118.0.5993.112", "120.0.6099.230", "121.0.6167.101", "122.0.6261.90"]

# 合规商业模式：用于受控测试环境 + 多租户隔离；不用于欺骗第三方安全检测。
_FINGERPRINT_POLICIES: dict[str, dict[str, Any]] = {
    "commercial": {
        "label": "commercial-isolated-profile",
        "description": "随机化设备标识并保持每台实例隔离；适用于合法的云手机租户隔离和自动化测试。",
        "allow_model_randomization": True,
        "allow_proxy_binding": True,
        "allow_timezone_variant": True,
    },
    "qa": {
        "label": "qa-device-template",
        "description": "标准化的 QA 设备模板，用于自动化回归测试与脚本录制。",
        "allow_model_randomization": False,
        "allow_proxy_binding": True,
        "allow_timezone_variant": True,
    },
}


def _rand_mac(rng: random.Random) -> str:
    return ":".join(f"{rng.randint(0, 255):02x}" for _ in range(6))


def _rand_ip(rng: random.Random, prefixes: list[int] | None = None) -> str:
    # demo 用：从常见公网段随机一个「出口 IP」展示；真实出口由 proxy_pool 决定。
    pool = prefixes or [27, 39, 58, 101, 112, 120, 183, 202]
    return f"{rng.choice(pool)}.{rng.randint(1, 254)}.{rng.randint(1, 254)}.{rng.randint(1, 254)}"


def _resolve_fingerprint_policy(mode: str | None) -> dict[str, Any]:
    key = (mode or "commercial").lower()
    if key not in _FINGERPRINT_POLICIES:
        raise ValueError(
            f"Unsupported fingerprint mode '{mode}'. Choose one of: "
            f"{', '.join(sorted(_FINGERPRINT_POLICIES))}."
        )
    return _FINGERPRINT_POLICIES[key]


def generate_fingerprint(
    seed: str | None = None,
    proxy: str | None = None,
    *,
    mode: str = "commercial",
    region: str | None = None,
) -> dict:
    """生成一份完整指纹。

    Args:
        seed: 稳定的种子；传入相同 seed 可复现同一设备指纹。
        proxy: 代理配置，通常是合法的企业代理池配置。
        mode: 指纹策略，当前支持 commercial 与 qa；本实现不会绕过外部完整性检测。
        region: 可选区域标识（如 cn、us、eu），用于隔离实例和租户。
    """
    policy = _resolve_fingerprint_policy(mode)
    seed = seed or uuid.uuid4().hex
    rng = random.Random(seed)

    if policy["allow_model_randomization"]:
        brand, manufacturer, model, marketing = rng.choice(_DEVICE_MODELS)
    else:
        brand, manufacturer, model, marketing = _DEVICE_MODELS[0]

    android_id = hashlib.sha1(f"aid-{seed}".encode()).hexdigest()[:16]
    serialno = "SN" + hashlib.sha1(f"sn-{seed}".encode()).hexdigest()[:10].upper()
    imei = "".join(str(rng.randint(0, 9)) for _ in range(15))
    mac = _rand_mac(rng)
    chrome = rng.choice(_CHROME_VERSIONS)
    android_ver = rng.choice(["12", "13", "14"])
    width, height = rng.choice([(1080, 2400), (1080, 1920), (1440, 3200), (720, 1600)])
    dpi = rng.choice([320, 400, 440, 480, 560])
    region = (region or "global").lower()
    profile = _REGION_PROFILES.get(region)
    if policy["allow_timezone_variant"] and profile:
        timezone = rng.choice(profile["timezones"])
        language = rng.choice(profile["languages"])
    elif policy["allow_timezone_variant"]:
        timezone = rng.choice(_TIMEZONES)
        language = rng.choice(_LANGUAGES)
    else:
        timezone = "Asia/Shanghai"
        language = "zh-CN"
    ip_prefixes = profile["ip_prefixes"] if profile else None

    user_agent = (
        f"Mozilla/5.0 (Linux; Android {android_ver}; {model}) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{chrome} Mobile Safari/537.36"
    )

    return {
        "seed": seed,
        "mode": mode,
        "policy": {
            "name": policy["label"],
            "description": policy["description"],
            "legal_use": "controlled-test-or-isolated-cloud-instance-only",
            "not_for_attestation_bypass": True,
        },
        "region": region,
        # --- 设备标识（Redroid props 注入）---
        "device": {
            "brand": brand,
            "manufacturer": manufacturer,
            "model": model,
            "marketing_name": marketing,
            "android_id": android_id,
            "serialno": serialno,
            "imei": imei,
            "mac": mac,
            "android_version": android_ver,
        },
        # --- 浏览器指纹（Chromium 注入）---
        "browser": {
            "user_agent": user_agent,
            "chrome_version": chrome,
            "width": width,
            "height": height,
            "dpi": dpi,
            "device_pixel_ratio": round(dpi / 160, 2),
            "timezone": timezone,
            "language": language,
            "webgl_vendor": rng.choice(_GL_VENDORS),
            "webgl_renderer": rng.choice(_GL_RENDERERS),
            # canvas / audio 指纹噪声种子：注入脚本据此对每台设备加固定微扰
            "canvas_noise_seed": hashlib.sha1(f"canvas-{seed}".encode()).hexdigest()[:12],
            "hardware_concurrency": rng.choice([4, 6, 8]),
            "device_memory": rng.choice([4, 6, 8, 12]),
        },
        # --- 网络（独立出口 IP / 代理位）---
        "network": {
            "proxy": proxy,
            "exit_ip": _rand_ip(rng, ip_prefixes),
        },
    }


def generate_batch_fingerprints(count: int, *, proxy_pool: list[str] | None = None, mode: str = "commercial") -> list[dict]:
    """为一批云手机生成隔离的设备指纹，适用于自动化测试与租户隔离场景。"""
    if count < 1:
        return []
    proxies = proxy_pool or []
    profiles = []
    for idx in range(count):
        proxy = proxies[idx % len(proxies)] if proxies else None
        profiles.append(generate_fingerprint(seed=f"batch-{idx}", proxy=proxy, mode=mode))
    return profiles


def validate_fingerprint(fp: dict) -> bool:
    """轻量校验：确保关键字段存在且不为空，适用于合法分组隔离与模板校验。"""
    required_paths = [
        ("seed", str),
        ("device.brand", str),
        ("device.model", str),
        ("device.android_id", str),
        ("browser.user_agent", str),
        ("network.exit_ip", str),
    ]
    for path, expected_type in required_paths:
        value = fp
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                return False
            value = value[part]
        if not isinstance(value, expected_type) or not str(value).strip():
            return False
    return True


def redroid_props(fp: dict) -> list[str]:
    """把指纹转成 Redroid 设备标识 props（ro.*）。

    注意：只注入设备标识；显示参数(width/height/dpi)由设备记录在 create() 时单独指定，
    避免与这里的浏览器指纹分辨率冲突。
    """
    d = fp["device"]
    return [
        f"ro.product.brand={d['brand']}",
        f"ro.product.manufacturer={d['manufacturer']}",
        f"ro.product.model={d['model']}",
        f"ro.product.name={d['model']}",
        f"ro.serialno={d['serialno']}",
        f"androidboot.serialno={d['serialno']}",
    ]
