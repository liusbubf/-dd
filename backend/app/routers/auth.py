"""登录鉴权：图形验证码 + 失败锁定 + 上次登录提示（V2-1）。

安全约定：
- 验证码 5 分钟有效、一次性消费（校验前即从存储移除，防重放）；
- 错误提示不区分「用户不存在 / 密码错误」，统一为「用户名或密码错误」；
- 同一「用户名 + IP」15 分钟内失败 5 次，锁定 5 分钟（429 + Retry-After）；
- 验证码/失败计数均存进程内存：单实例够用；多副本部署需换 Redis（见交付报告风险）。
"""
from __future__ import annotations

import asyncio
import base64
import random
import secrets
import time
import uuid
from datetime import datetime, timezone
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import create_access_token, get_current_user, verify_password
from ..config import settings
from ..database import get_db
from ..models import User
from ..rbac import record_audit
from ..schemas import CaptchaOut, LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

_CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CAPTCHA_TTL = 300

# captcha_id -> {"code": str, "expires": float}
_captchas: dict[str, dict] = {}
_captcha_lock = asyncio.Lock()

# "username|ip" -> {"fails": [ts], "locked_until": ts}
_login_fails: dict[str, dict] = {}
_fail_lock = asyncio.Lock()


def _gen_code(n: int = 4) -> str:
    return "".join(secrets.choice(_CAPTCHA_CHARS) for _ in range(n))


def _captcha_svg(code: str) -> str:
    width, height = 120, 44
    palette = ("#31405a", "#3f5a8a", "#4a4458", "#2f5f57", "#5a4a32")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#f4f7fc"/><stop offset="1" stop-color="#e6ebf5"/>'
        "</linearGradient></defs>",
        '<rect width="100%" height="100%" fill="url(#g)"/>',
    ]
    # 干扰线 / 干扰点（不遮盖字符主区域）
    for _ in range(5):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#9fb0c8" '
            f'stroke-width="{random.choice((1, 1, 2))}" opacity="0.55"/>'
        )
    for _ in range(18):
        cx, cy = random.randint(0, width), random.randint(0, height)
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="1" fill="#a9b6c9" opacity="0.7"/>')
    # 字符：随机位置/旋转/颜色
    for i, ch in enumerate(code):
        x = 18 + i * 24 + random.randint(-2, 2)
        y = 31 + random.randint(-3, 3)
        rot = random.randint(-16, 16)
        color = random.choice(palette)
        parts.append(
            f'<text x="{x}" y="{y}" font-size="23" font-family="Arial,Helvetica,sans-serif" '
            f'font-weight="700" fill="{color}" transform="rotate({rot} {x} {y})">'
            f"{xml_escape(ch)}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


async def _issue_captcha() -> CaptchaOut:
    code = _gen_code()
    captcha_id = uuid.uuid4().hex
    now = time.monotonic()
    svg = _captcha_svg(code)
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    async with _captcha_lock:
        # 顺手清理过期项，避免内存无限增长
        for cid in [c for c, v in _captchas.items() if v["expires"] <= now]:
            _captchas.pop(cid, None)
        _captchas[captcha_id] = {"code": code.lower(), "expires": now + _CAPTCHA_TTL}
    return CaptchaOut(
        captcha_id=captcha_id,
        image=f"data:image/svg+xml;base64,{encoded}",
        expires_in=_CAPTCHA_TTL,
    )


async def _consume_captcha(captcha_id: str, code: str) -> bool:
    """一次性消费：无论对错都删除，防止暴力试同一个验证码。"""
    now = time.monotonic()
    async with _captcha_lock:
        item = _captchas.pop(captcha_id, None)
    if item is None or item["expires"] <= now:
        return False
    return secrets.compare_digest(item["code"], (code or "").strip().lower())


async def _check_and_record_fail(key: str) -> int:
    """记录一次失败；返回剩余锁定秒数（0 表示未锁定）。"""
    now = time.monotonic()
    window = settings.login_fail_window
    async with _fail_lock:
        rec = _login_fails.setdefault(key, {"fails": [], "locked_until": 0.0})
        if rec["locked_until"] > now:
            return int(rec["locked_until"] - now) + 1
        rec["fails"] = [t for t in rec["fails"] if now - t < window]
        rec["fails"].append(now)
        if len(rec["fails"]) >= settings.login_fail_limit:
            rec["locked_until"] = now + settings.login_lock_seconds
            return settings.login_lock_seconds
        return 0


async def _locked_seconds(key: str) -> int:
    now = time.monotonic()
    async with _fail_lock:
        rec = _login_fails.get(key)
        if rec and rec["locked_until"] > now:
            return int(rec["locked_until"] - now) + 1
        return 0


async def _reset_fails(key: str) -> None:
    async with _fail_lock:
        _login_fails.pop(key, None)


def _ip_location(ip: str) -> str | None:
    """IP 粗略归属。

    不引外部 GEO 服务：内网/本机给出可读归属，公网 IP 返回 None，
    前端按「取不到就只显示时间与 IP」降级。生产可在此接 IP 库，不影响接口形状。
    """
    if not ip or ip in ("unknown", "127.0.0.1", "::1"):
        return "本机"
    if ip.startswith(("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.")):
        return "内网"
    return None


@router.get("/captcha", response_model=CaptchaOut)
async def captcha() -> CaptchaOut:
    return await _issue_captcha()


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    ip = request.client.host if request.client else "unknown"
    fail_key = f"{body.username}|{ip}"

    locked = await _locked_seconds(fail_key)
    if locked:
        raise HTTPException(
            429,
            f"登录失败次数过多，请在 {locked} 秒后重试",
            headers={"Retry-After": str(locked)},
        )

    if settings.login_captcha_enabled:
        if not body.captcha_id or not body.captcha_code:
            _ = await _check_and_record_fail(fail_key)
            raise HTTPException(400, "请输入图形验证码")
        if not await _consume_captcha(body.captcha_id, body.captcha_code):
            _ = await _check_and_record_fail(fail_key)
            raise HTTPException(400, "验证码错误或已过期，请刷新后重试")

    user = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        remaining_lock = await _check_and_record_fail(fail_key)
        if remaining_lock:
            raise HTTPException(
                429,
                f"登录失败次数过多，请在 {remaining_lock} 秒后重试",
                headers={"Retry-After": str(remaining_lock)},
            )
        # 不区分「用户不存在 / 密码错误」，避免账号枚举
        raise HTTPException(401, "用户名或密码错误")

    # 检查账号是否被封禁
    if user.is_banned:
        reason = user.banned_reason or "违反平台服务条款"
        raise HTTPException(403, f"账号已被封禁：{reason}")

    await _reset_fails(fail_key)

    prev_at = user.last_login_at
    prev_ip = user.last_login_ip
    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = ip
    await db.commit()

    last_login: dict[str, str | None] | None = None
    if prev_at is not None:
        last_login = {
            "at": prev_at.isoformat(),
            "ip": prev_ip,
            "location": _ip_location(prev_ip) if prev_ip else None,
        }
    await record_audit(
        db,
        user.username,
        "auth.login",
        target=f"ip {ip}",
        detail={"location": _ip_location(ip)},
    )

    return TokenResponse(
        access_token=create_access_token(user.username),
        user=UserOut.model_validate(user),
        last_login=last_login,
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
