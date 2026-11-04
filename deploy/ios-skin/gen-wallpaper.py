#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 iOS 风格壁纸（720x1280），纯标准库实现（Mac 上无 PIL/imagemagick 也能跑）。
效果：蓝→紫→粉 的平滑对角渐变 + 轻微径向高光，接近 iOS 默认壁纸观感。
用法: python3 gen-wallpaper.py [输出路径]
"""
import sys, zlib, struct, math

W, H = 720, 1280
OUT = sys.argv[1] if len(sys.argv) > 1 else "ios-wallpaper.png"

# 三个渐变锚点（RGB）：顶部偏蓝、中部偏紫、底部偏粉
C_TOP = (46, 91, 214)     # 蓝
C_MID = (120, 80, 210)    # 紫
C_BOT = (232, 121, 190)   # 粉


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return tuple(lerp(c1[i], c2[i], t) for i in range(3))


# 高光中心（相对坐标）
GX, GY = 0.32, 0.28
GR = 0.75  # 高光半径


def build_row(y):
    row = bytearray()
    row.append(0)  # PNG filter type 0 (None)
    vy = y / (H - 1)
    for x in range(W):
        vx = x / (W - 1)
        # 对角参数 t：左上(0) -> 右下(1)
        t = (vx * 0.35 + vy * 0.65)
        if t < 0.5:
            base = mix(C_TOP, C_MID, t / 0.5)
        else:
            base = mix(C_MID, C_BOT, (t - 0.5) / 0.5)
        # 径向高光：靠近 (GX,GY) 提亮
        dx = (vx - GX)
        dy = (vy - GY)
        d = math.sqrt(dx * dx + dy * dy)
        glow = max(0.0, 1.0 - d / GR)
        glow = glow * glow * 0.28  # 高光强度
        r = base[0] + (255 - base[0]) * glow
        g = base[1] + (255 - base[1]) * glow
        b = base[2] + (255 - base[2]) * glow
        row.append(int(max(0, min(255, r))))
        row.append(int(max(0, min(255, g))))
        row.append(int(max(0, min(255, b))))
    return bytes(row)


def png_chunk(tag, data):
    c = struct.pack(">I", len(data)) + tag + data
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return c + struct.pack(">I", crc)


def main():
    raw = bytearray()
    for y in range(H):
        raw += build_row(y)
    comp = zlib.compress(bytes(raw), 9)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)  # 8-bit, color type 2 (RGB)
    png = sig + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", comp) + png_chunk(b"IEND", b"")
    with open(OUT, "wb") as f:
        f.write(png)
    print("wrote", OUT, len(png), "bytes", W, "x", H)


if __name__ == "__main__":
    main()
