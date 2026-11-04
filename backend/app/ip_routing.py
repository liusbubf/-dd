"""IP 选路收敛：显式绑定优先，代理池兜底。

过去「设备绑定 IP」与「一键新机换 IP」是两套逻辑：
- ips.bind 只写 device.ip_id + 指纹 network；
- 一键新机在 rotate_proxy 时无条件调 pick_proxy 随机换出口，
  导致绑定关系被悄悄绕开，绑定后新机 IP 又变了。

现在统一到本模块：
- resolve_proxy：有可用绑定 → 一定返回绑定代理；没有绑定且允许轮换 → 才走代理池；
- apply_bound_network：把绑定信息刷回设备指纹，供新机/开网页等场景复用。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from .models import Device, IpResource
from .orchestrator.base import pick_proxy


def proxy_from_record(rec: IpResource | None) -> str | None:
    """把 IP 资源记录转成代理串；无端口视为直连（返回 None）。"""
    if rec is None or rec.port <= 0:
        return None
    cred = f"{rec.username}:{rec.password}@" if rec.username else ""
    return f"http://{cred}{rec.ip}:{rec.port}"


def current_proxy(device: Device) -> str | None:
    net = (device.fingerprint or {}).get("network") or {}
    return net.get("proxy")


async def resolve_proxy(
    db: AsyncSession, device: Device, *, rotate: bool = False
) -> str | None:
    """解析设备最终出口代理。

    规则（顺序固定，保证幂等）：
    1. 设备有绑定 IP 且未被停用 → 一定用绑定代理（即使 rotate=True 也不换）；
    2. 无绑定 / 绑定已停用 → 保持当前代理；
    3. 仅当 rotate=True 且无可用绑定时，才从代理池挑一个新的。
    """
    current = current_proxy(device)
    if device.ip_id:
        rec = await db.get(IpResource, device.ip_id)
        if rec is not None and rec.status != "disabled":
            return proxy_from_record(rec) or current
    if not rotate:
        return current
    return pick_proxy(current) or current


async def apply_bound_network(db: AsyncSession, device: Device) -> bool:
    """把绑定 IP 写回设备指纹（network.exit_ip / network.proxy）。

    返回是否应用了绑定。绑定停用或资源不存在时返回 False，不改指纹。
    """
    if not device.ip_id:
        return False
    rec = await db.get(IpResource, device.ip_id)
    if rec is None or rec.status == "disabled":
        return False

    fp = dict(device.fingerprint or {})
    net = dict(fp.get("network") or {})
    net["exit_ip"] = rec.ip
    proxy = proxy_from_record(rec)
    if proxy:
        net["proxy"] = proxy
    else:
        net.pop("proxy", None)
    fp["network"] = net
    device.fingerprint = fp
    flag_modified(device, "fingerprint")
    return True
