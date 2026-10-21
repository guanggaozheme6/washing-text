#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 WashingText.ico —— 与界面顶栏同款的水滴标识.

纯标准库实现 (多边形扫描 + zlib 编 PNG + ICO 封包), 不引入 Pillow:
项目依赖已经够重, 打包工具链不该再拖一个新库进来.

用法: .venv/Scripts/python.exe build/make_icon.py
"""
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'WashingText.ico')
SIZES = (16, 24, 32, 48, 64, 128, 256)

BG_TOP = (0x4A, 0x84, 0xAD)
BG_BOTTOM = (0x2B, 0x54, 0x72)
FG = (0xFF, 0xFF, 0xFF)

# 品牌标识路径 (viewBox 0 0 32 32), 三次贝塞尔转采样点
DROP_SEGS = [
    ((16.0, 4.0), (10.5, 4.0), (7.0, 8.2), (7.0, 13.4)),
    ((7.0, 13.4), (7.0, 18.3), (10.6, 24.0), (16.0, 28.0)),
    ((16.0, 28.0), (21.4, 24.0), (25.0, 18.3), (25.0, 13.4)),
    ((25.0, 13.4), (25.0, 8.2), (21.5, 4.0), (16.0, 4.0)),
]
# 内部两条线: 横拱线 + 竖线, 用"点到线段距离"做镂空
INNER_LINES = [
    [((11.5, 13.5), (13.1, 14.6), (18.9, 14.6), (20.5, 13.5))],
    [((16.0, 10.0), (16.0, 10.0), (16.0, 18.0), (16.0, 18.0))],
]


def bezier(p0, p1, p2, p3, n=20):
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        x = u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0]
        y = u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]
        pts.append((x, y))
    return pts


def build_polygon():
    poly = []
    for seg in DROP_SEGS:
        poly.extend(bezier(*seg)[:-1])
    return poly


POLY = build_polygon()


def point_in_poly(x, y):
    inside = False
    n = len(POLY)
    for i in range(n):
        x1, y1 = POLY[i]
        x2, y2 = POLY[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xin:
                inside = not inside
    return inside


def dist_to_seg(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return ((px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2) ** 0.5


INNER_SEGS = []
for line in INNER_LINES:
    pts = bezier(*line[0], n=16) if line[0][1] != line[0][2] or line[0][1] != line[0][3] else [line[0][0], line[0][3]]
    for i in range(len(pts) - 1):
        INNER_SEGS.append((pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]))


def sample(px, py):
    """32x32 坐标系下返回 RGBA."""
    # 水滴
    if point_in_poly(px, py):
        for x1, y1, x2, y2 in INNER_SEGS:
            if dist_to_seg(px, py, x1, y1, x2, y2) < 0.72:
                return None            # 镂空, 交给背景
        return FG
    return None


def render(size):
    """渲染单张 RGBA 位图. 背景圆角方块 + 白色水滴."""
    ss = 3                            # 3x3 超采样, 抗锯齿够用且不至于太慢
    radius = size * 0.22
    scale = size * 0.80 / 32.0
    off = (size - 32 * scale) / 2.0

    px = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            r = g = b = a = 0.0
            for sy in range(ss):
                for sx in range(ss):
                    fx = x + (sx + 0.5) / ss
                    fy = y + (sy + 0.5) / ss
                    # 圆角矩形遮罩
                    cx = min(max(fx, radius), size - radius)
                    cy = min(max(fy, radius), size - radius)
                    if (fx - cx) ** 2 + (fy - cy) ** 2 > radius ** 2:
                        continue
                    u = (fx - off) / scale
                    v = (fy - off) / scale
                    fg = sample(u, v)
                    if fg is None:
                        t = fy / size
                        col = tuple(
                            int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t)
                            for i in range(3))
                    else:
                        col = fg
                    r += col[0]
                    g += col[1]
                    b += col[2]
                    a += 255
            total = ss * ss
            i = (y * size + x) * 4
            if a:
                cov = a / total
                px[i + 0] = int(r / (a / 255))
                px[i + 1] = int(g / (a / 255))
                px[i + 2] = int(b / (a / 255))
                px[i + 3] = int(cov)
            else:
                px[i + 3] = 0
    return bytes(px)


def png_chunk(tag, data):
    return (struct.pack('>I', len(data)) + tag + data
            + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))


def to_png(size, rgba):
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)
        raw.extend(rgba[y * stride:(y + 1) * stride])
    return (b'\x89PNG\r\n\x1a\n'
            + png_chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
            + png_chunk(b'IDAT', zlib.compress(bytes(raw), 9))
            + png_chunk(b'IEND', b''))


def main():
    frames = []
    for size in SIZES:
        print(f'渲染 {size}x{size} …')
        frames.append((size, to_png(size, render(size))))

    count = len(frames)
    header = struct.pack('<HHH', 0, 1, count)
    entries, blobs = b'', b''
    offset = 6 + 16 * count
    for size, png in frames:
        dim = 0 if size >= 256 else size
        entries += struct.pack('<BBBBHHII', dim, dim, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        blobs += png
    with open(OUT, 'wb') as f:
        f.write(header + entries + blobs)
    print(f'已生成 {OUT} ({os.path.getsize(OUT) / 1024:.1f} KB)')


if __name__ == '__main__':
    main()
