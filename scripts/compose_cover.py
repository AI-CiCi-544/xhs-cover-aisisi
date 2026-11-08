#!/usr/bin/env python3
"""
视频封面合成器：背景图 + 精确中文排版叠字。

为什么要有这个脚本：
AI 生图直出中文标题必然糊字、错字、断行失控。正确做法是 AI 只出「无文字背景」，
标题/角标/高亮块由本脚本用真实字体渲染 —— 中文 100% 清晰，字号行距可复算，能批量出稿。

用法：
    python3 compose_cover.py spec.json                      # 输出到 spec 里指定的 path
    python3 compose_cover.py spec.json -o out/cover.png     # 覆盖输出路径
    python3 compose_cover.py spec.json --thumb-only         # 只出信息流缩略预览图
    python3 compose_cover.py spec.json --safe-debug         # 叠加安全区参考线

spec.json 结构见 references/spec-schema.md，可用的完整示例见 assets/spec-douyin-bigtext.json
"""

import argparse
import json
import os
import sys
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------- 字体解析

FONT_DIRS = [
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/Library/Fonts",
    os.path.expanduser("~/Library/Fonts"),
    "/usr/share/fonts",
    "/usr/local/share/fonts",
]

# role -> [(文件名, TTC 内索引)]，按优先级排列。索引对应 ttc 集合里的字面。
FONT_CANDIDATES: dict[str, list[tuple[str, int]]] = {
    "heavy": [
        ("Hiragino Sans GB.ttc", 2),          # 冬青黑体 W6
        ("STHeiti Medium.ttc", 1),            # 华文黑体 Medium
        ("NotoSansCJK-Bold.ttc", 2),
        ("NotoSansCJKsc-Bold.otf", 0),
        ("SourceHanSansSC-Bold.otf", 0),
        ("NotoSansSC-Bold.otf", 0),
        ("wqy-zenhei.ttc", 0),
    ],
    "medium": [
        ("Hiragino Sans GB.ttc", 0),          # 冬青黑体 W3
        ("STHeiti Medium.ttc", 1),
        ("NotoSansCJK-Regular.ttc", 2),
        ("NotoSansCJKsc-Regular.otf", 0),
        ("SourceHanSansSC-Regular.otf", 0),
        ("NotoSansSC-Regular.otf", 0),
    ],
    "light": [
        ("Hiragino Sans GB.ttc", 0),
        ("STHeiti Light.ttc", 1),
        ("NotoSansCJK-Regular.ttc", 2),
        ("NotoSansSC-Regular.otf", 0),
    ],
    "serif_black": [
        ("Songti.ttc", 0),                    # 宋体 Black，高级感主标题
        ("NotoSerifCJK-Bold.ttc", 2),
        ("SourceHanSerifSC-Bold.otf", 0),
        ("Songti.ttc", 1),
    ],
    "serif": [
        ("Songti.ttc", 1),
        ("NotoSerifCJK-Regular.ttc", 2),
        ("SourceHanSerifSC-Regular.otf", 0),
        ("Songti.ttc", 3),
    ],
    "latin": [
        ("HelveticaNeue.ttc", 0),
        ("Helvetica.ttc", 0),
        ("Arial.ttf", 0),
        ("DejaVuSans-Bold.ttf", 0),
    ],
}

_index_cache: dict[str, str] | None = None
_font_cache: dict[tuple[str, int, int], ImageFont.FreeTypeFont] = {}


def _font_index() -> dict[str, str]:
    """扫描系统字体目录，建立 文件名 -> 绝对路径 索引（只扫三层，避免拖慢）。"""
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    idx: dict[str, str] = {}
    for d in FONT_DIRS:
        if not os.path.isdir(d):
            continue
        base_depth = d.rstrip(os.sep).count(os.sep)
        for root, dirs, files in os.walk(d):
            if root.count(os.sep) - base_depth >= 3:
                dirs[:] = []
            for f in files:
                if f.lower().endswith((".ttc", ".ttf", ".otf")):
                    idx.setdefault(f, os.path.join(root, f))
    _index_cache = idx
    return idx


def resolve_font(role: str, size: int, override_path: str | None = None,
                 override_index: int = 0) -> ImageFont.FreeTypeFont:
    key = (override_path or role, override_index, size)
    if key in _font_cache:
        return _font_cache[key]

    if override_path:
        font = ImageFont.truetype(override_path, size, index=override_index)
        _font_cache[key] = font
        return font

    idx = _font_index()
    errs = []
    for name, face_index in FONT_CANDIDATES.get(role, FONT_CANDIDATES["medium"]):
        path = idx.get(name)
        if not path:
            continue
        try:
            font = ImageFont.truetype(path, size, index=face_index)
            _font_cache[key] = font
            return font
        except Exception as e:  # noqa: BLE001
            errs.append(f"{path}#{face_index}: {e}")
    raise RuntimeError(
        f"找不到可用的中文字体（role={role}）。已尝试：{FONT_CANDIDATES.get(role)}\n"
        f"失败详情：{errs}\n"
        "解决：在 spec 的 text 项里显式写 \"font_path\" 和 \"font_index\"，"
        "或把字体文件放进 /Library/Fonts。"
    )


# ---------------------------------------------------------------- 基础工具

def parse_color(value: Any, opacity: float | None = None) -> tuple[int, int, int, int]:
    """支持 #RGB / #RRGGBB / #RRGGBBAA / [r,g,b] / [r,g,b,a]。"""
    if isinstance(value, (list, tuple)):
        rgba = list(value) + [255] * (4 - len(value))
        a = int(rgba[3] * opacity) if opacity is not None else int(rgba[3])
        return int(rgba[0]), int(rgba[1]), int(rgba[2]), a
    s = str(value).strip()
    if not s.startswith("#"):
        s = {"white": "#FFFFFF", "black": "#000000"}.get(s.lower(), s)
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    a = int(s[6:8], 16) if len(s) >= 8 else 255
    if opacity is not None:
        a = int(a * opacity)
    return r, g, b, a


def norm(v: float, total: int) -> int:
    """0~1 的归一化坐标换算成像素；大于 1 的值按像素直接用。"""
    return int(round(v * total)) if isinstance(v, (int, float)) and abs(v) <= 2 else int(v)


def luminance(rgb: tuple[int, int, int]) -> float:
    def chan(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ---------------------------------------------------------------- 背景处理

def load_background(spec: dict, W: int, H: int) -> Image.Image:
    bg = spec.get("background", {}) or {}
    btype = bg.get("type", "color")

    if btype == "image":
        path = bg["path"]
        if not os.path.isabs(path):
            path = os.path.join(spec.get("_base_dir", "."), path)
        img = Image.open(path).convert("RGB")
        fit = bg.get("fit", "cover")
        fx, fy = (bg.get("focus") or [0.5, 0.5])[:2]
        if fit == "cover":
            scale = max(W / img.width, H / img.height) * bg.get("zoom", 1.0)
            img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale)),
                              ), Image.LANCZOS)
        elif fit == "contain":
            scale = min(W / img.width, H / img.height) * bg.get("zoom", 1.0)
            img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                             Image.LANCZOS)
        canvas = Image.new("RGB", (W, H), parse_color(bg.get("pad_color", "#000000"))[:3])
        left = int(round((W - img.width) * fx))
        top = int(round((H - img.height) * fy))
        canvas.paste(img, (left, top))
        img = canvas
    elif btype == "gradient":
        stops = bg.get("stops") or ["#1B1B26", "#0B0B12"]
        img = Image.new("RGB", (W, H))
        direction = bg.get("direction", "vertical")
        n = H if direction == "vertical" else W
        line = Image.new("RGB", (n, 1))
        px = line.load()
        colors = [parse_color(c)[:3] for c in stops]
        for i in range(n):
            t = i / max(1, n - 1) * (len(colors) - 1)
            a, b = colors[int(t)], colors[min(len(colors) - 1, int(t) + 1)]
            f = t - int(t)
            px[i, 0] = tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3))
        img = line.resize((W, H)) if direction == "vertical" else line.resize((W, H))
    else:
        img = Image.new("RGB", (W, H), parse_color(bg.get("color", "#111118"))[:3])

    from PIL import ImageEnhance
    if bg.get("blur"):
        img = img.filter(ImageFilter.GaussianBlur(float(bg["blur"]) * min(W, H) / 1000))
    if bg.get("brightness") is not None:
        img = ImageEnhance.Brightness(img).enhance(float(bg["brightness"]))
    if bg.get("saturation") is not None:
        img = ImageEnhance.Color(img).enhance(float(bg["saturation"]))
    if bg.get("contrast") is not None:
        img = ImageEnhance.Contrast(img).enhance(float(bg["contrast"]))
    return img


def apply_treatments(img: Image.Image, treatments: list[dict], W: int, H: int) -> Image.Image:
    base = img.convert("RGBA")
    for t in treatments:
        kind = t.get("type")
        color = parse_color(t.get("color", "#000000"), t.get("opacity", 0.5))

        if kind == "scrim":
            side = t.get("side", "bottom")
            extent = max(1, norm(t.get("height", 0.4),
                                 H if side in ("top", "bottom") else W))
            gamma = float(t.get("feather", 1.0))
            # 边缘处 alpha 最强，向内线性 fade；gamma<1 更柔，gamma>1 更硬
            ramp = [int(255 * (1 - (i / max(1, extent - 1)) ** gamma)) for i in range(extent)]
            if side in ("bottom", "right"):
                ramp = ramp[::-1]
            mask = Image.new("L", (W, H), 0)
            if side in ("top", "bottom"):
                band = Image.new("L", (1, extent))
                band.putdata(ramp)
                mask.paste(band.resize((W, extent), Image.BILINEAR),
                           (0, 0 if side == "top" else H - extent))
            else:
                band = Image.new("L", (extent, 1))
                band.putdata(ramp)
                mask.paste(band.resize((extent, H), Image.BILINEAR),
                           (0 if side == "left" else W - extent, 0))
            layer = Image.new("RGBA", (W, H), color)
            layer.putalpha(mask.point(lambda v: int(v * color[3] / 255)))
            base = Image.alpha_composite(base, layer)

        elif kind == "vignette":
            strength = float(t.get("strength", 0.35))
            small = 96
            cx = cy = (small - 1) / 2
            maxd = (2 ** 0.5) * cx
            data = []
            for y in range(small):
                for x in range(small):
                    d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / maxd
                    data.append(int(255 * strength * min(1.0, d ** 2.2)))
            mask = Image.new("L", (small, small))
            mask.putdata(data)
            mask = mask.resize((W, H), Image.BILINEAR)
            layer = Image.new("RGBA", (W, H), color)
            layer.putalpha(mask)
            base = Image.alpha_composite(base, layer)

    return base


# ---------------------------------------------------------------- 文字排版

def _measure(text: str, font: ImageFont.FreeTypeFont,
             letter_spacing: float = 0.0) -> float:
    if not text:
        return 0.0
    return font.getlength(text) + letter_spacing * (len(text) - 1)


_TOKEN_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'-")


def _tokens(line: str) -> list[str]:
    """把一行切成排版单元：英文/数字按词，CJK 逐字，标点跟随前一个字。"""
    out: list[str] = []
    buf = ""
    for ch in line:
        if ch in _TOKEN_SAFE:
            buf += ch
        else:
            if buf:
                out.append(buf)
                buf = ""
            if ch == " ":
                out.append(" ")
            elif ch in "，。！？、：；）」』%”’":
                if out:
                    out[-1] += ch
                else:
                    out.append(ch)
            else:
                out.append(ch)
    if buf:
        out.append(buf)
    return out


def _wrap(paragraph: str, font: ImageFont.FreeTypeFont, max_w: float,
          letter_spacing: float) -> list[str]:
    if max_w <= 0:
        return [paragraph]
    lines: list[str] = []
    cur = ""
    for tok in _tokens(paragraph):
        trial = cur + tok
        if _measure(trial.rstrip(), font, letter_spacing) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur.rstrip())
            cur = "" if tok == " " else tok
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


def layout_block(item: dict, W: int, H: int) -> dict:
    """计算字号、断行、块尺寸。返回排版结果字典。"""
    content = str(item.get("content", ""))
    ls_ratio = float(item.get("line_spacing", 1.18))
    letter_ratio = float(item.get("letter_spacing", 0.0))
    stroke_w = float((item.get("stroke") or {}).get("width", 0))
    box_w = norm(item.get("box_width", 0.84), W) - stroke_w * 2
    box_h = norm(item["box_height"], H) if item.get("box_height") else None

    auto = item.get("auto_fit")
    if item.get("vertical"):
        explicit = [list(p) for p in content.split("\n")]
        paragraphs = ["\n".join(p) for p in explicit]
    else:
        paragraphs = content.split("\n")

    def attempt(size: int):
        font = resolve_font(item.get("font", "heavy"), size, item.get("font_path"),
                            int(item.get("font_index", 0)))
        spacing = letter_ratio * size
        if item.get("vertical"):
            lines = [ch for ch in content if ch != "\n"] or [""]
            widths = [_measure(ch, font, 0) for ch in lines]
            block_w = max(widths) if widths else 0
            line_h = int(round(size * float(item.get("line_spacing", 1.06))))
            block_h = line_h * len(lines)
        else:
            lines, block_w, line_h = [], 0, int(round(size * ls_ratio))
            for p in paragraphs:
                wrapped = _wrap(p, font, box_w, spacing)
                lines.extend(wrapped)
                block_w = max(block_w, max((_measure(l, font, spacing) for l in wrapped), default=0))
            block_h = line_h * len(lines)
        block_w += stroke_w * 2
        block_h += stroke_w * 2
        max_lines = int((auto or {}).get("max_lines", 4))
        ok = block_w <= box_w + 1 and (box_h is None or block_h <= box_h) and len(lines) <= max_lines
        return ok, dict(font=font, size=size, spacing=spacing, lines=lines, line_h=line_h,
                        block_w=int(round(block_w)), block_h=block_h)

    if auto or not item.get("size"):
        lo = int((auto or {}).get("min", 44))
        hi = int((auto or {}).get("max", item.get("size") or int(H * 0.16)))
        best = None
        # 从小到大找最大的可行字号
        while lo <= hi:
            mid = (lo + hi) // 2
            ok, res = attempt(mid)
            if ok:
                best = res
                lo = mid + 1
            else:
                hi = mid - 1
        if best is None:
            ok, best = attempt(int((auto or {}).get("min", 44)))
            if not ok:
                print(f"[warn] 标题在最小字号下仍放不下，可能撑破安全区：{content[:24]!r}",
                      file=sys.stderr)
        return best
    ok, res = attempt(int(item["size"]))
    if not ok:
        print(f"[warn] 固定字号 {item['size']} 下文本超出盒子：{content[:24]!r}", file=sys.stderr)
    return res


def draw_text_block(layer: Image.Image, item: dict, lay: dict, W: int, H: int,
                    color_override: tuple[int, int, int, int] | None = None) -> None:
    """在透明图层上按排版结果写字（逐字绘制以支持字间距）。"""
    draw = ImageDraw.Draw(layer)
    font, size = lay["font"], lay["size"]
    stroke_w = float((item.get("stroke") or {}).get("width", 0))
    stroke_col = parse_color((item.get("stroke") or {}).get("color", "#000000"))
    fill = color_override or parse_color(item.get("color", "#FFFFFF"))
    align = item.get("align", "left")

    bx = norm(item.get("x", 0.08), W)
    by = norm(item.get("y", 0.5), H)
    block_w = lay["block_w"]
    cursor_y = by + stroke_w
    for line in lay["lines"]:
        lw = _measure(line, font, lay["spacing"])
        if align == "center":
            x = bx + (block_w - lw) / 2
        elif align == "right":
            x = bx + block_w - lw
        else:
            x = bx
        for ch in line:
            draw.text((x, cursor_y), ch, font=font, fill=fill, anchor="la",
                      stroke_width=int(stroke_w), stroke_fill=stroke_col)
            x += font.getlength(ch) + lay["spacing"]
        cursor_y += lay["line_h"]


def text_bbox(item: dict, lay: dict, W: int, H: int) -> tuple[int, int, int, int]:
    x = norm(item.get("x", 0.08), W)
    y = norm(item.get("y", 0.5), H)
    return int(x), int(y), int(x + lay["block_w"]), int(y + lay["block_h"])


def mean_bg_luminance(img: Image.Image, bbox: tuple[int, int, int, int]) -> float:
    """文字区域下方背景的平均亮度（0~255），用于算对比度。"""
    from PIL import ImageStat
    crop = img.crop(bbox).convert("RGB")
    crop.thumbnail((32, 32))
    r, g, b = ImageStat.Stat(crop).mean
    return luminance((r, g, b)) * 255


def _ink_box(item: dict, lay: dict, W: int, H: int) -> tuple[float, float, float, float]:
    """字形实际着墨范围（不含行距留白），用于让高亮块/徽章贴合文字。"""
    bx, by, bx2, by2 = text_bbox(item, lay, W, H)
    font = lay["font"]
    stroke = float((item.get("stroke") or {}).get("width", 0))
    gb = font.getbbox("签")  # 用字面最满的汉字取上下边界，避免 Abc 之类偏高的字失真
    return (bx + gb[0] - stroke, by + gb[1] - stroke,
            bx2 + gb[0] - stroke, by + (len(lay["lines"]) - 1) * lay["line_h"] + gb[3] + stroke)


def render_text(img: Image.Image, item: dict, lay: dict, W: int, H: int) -> Image.Image:
    shadow_cfg = item.get("shadow") or {}
    highlight = item.get("highlight") or {}

    if highlight:
        hl_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(hl_layer)
        pad_x = lay["size"] * float(highlight.get("pad_x", 0.42))
        pad_y = lay["size"] * float(highlight.get("pad_y", 0.30))
        ix1, iy1, ix2, iy2 = _ink_box(item, lay, W, H)
        mode = highlight.get("mode", "block")
        boxes = []
        if mode == "line":  # 逐行高亮，更像马克笔划过
            oy = iy1
            for line in lay["lines"]:
                lw = _measure(line, lay["font"], lay["spacing"])
                boxes.append((ix1, oy, ix1 + lw, oy + (iy2 - iy1) / len(lay["lines"])))
                oy += lay["line_h"]
        else:
            boxes.append((ix1, iy1, ix2, iy2))
        col = parse_color(highlight.get("color", "#FFD400"),
                          float(highlight.get("opacity", 1.0)))
        for b in boxes:
            r_spec = highlight.get("radius", 0.14)
            if r_spec == "pill":
                r = int((b[3] - b[1]) / 2) + int(pad_y)
            else:
                r = int(lay["size"] * float(r_spec))
            d.rounded_rectangle([b[0] - pad_x, b[1] - pad_y, b[2] + pad_x, b[3] + pad_y],
                                radius=max(2, r), fill=col)
        img = Image.alpha_composite(img, hl_layer)

    if shadow_cfg:
        sh_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw_text_block(sh_layer, item, lay, W, H,
                        color_override=parse_color(shadow_cfg.get("color", "#000000")))
        blur = float(shadow_cfg.get("blur", 0)) * min(W, H) / 1000
        if blur > 0:
            sh_layer = sh_layer.filter(ImageFilter.GaussianBlur(blur))
        alpha = sh_layer.getchannel("A").point(
            lambda v: int(v * float(shadow_cfg.get("opacity", 0.5))))
        sh_layer.putalpha(alpha)
        dx, dy = int(shadow_cfg.get("dx", 0)), int(shadow_cfg.get("dy", 0))
        if dx or dy:
            sh_layer = sh_layer.transform(sh_layer.size, Image.AFFINE,
                                          (1, 0, -dx, 0, 1, -dy))
        img = Image.alpha_composite(img, sh_layer)

    txt_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_text_block(txt_layer, item, lay, W, H)
    return Image.alpha_composite(img, txt_layer)


def render_shapes(img: Image.Image, shapes: list[dict], W: int, H: int) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for s in shapes:
        kind = s.get("type", "rect")
        color = parse_color(s.get("color", "#FFFFFF"), float(s.get("opacity", 1.0)))
        if kind == "line":
            d.line([norm(s["x1"], W), norm(s["y1"], H), norm(s["x2"], W), norm(s["y2"], H)],
                   fill=color, width=max(1, int(s.get("width", 4))))
        elif kind == "polygon":
            d.polygon([(norm(p[0], W), norm(p[1], H)) for p in s["points"]], fill=color)
        elif kind == "ellipse":
            d.ellipse([norm(s["x"], W), norm(s["y"], H),
                       norm(s["x"] + s["w"], W), norm(s["y"] + s["h"], H)], fill=color)
        else:
            radius = s.get("radius")
            if radius == "pill":
                radius = (norm(s["h"], H)) // 2
            d.rounded_rectangle([norm(s["x"], W), norm(s["y"], H),
                                 norm(s["x"] + s["w"], W), norm(s["y"] + s["h"], H)],
                                radius=int(radius or 0), fill=color)
    return Image.alpha_composite(img, layer)


def safe_debug(img: Image.Image, W: int, H: int) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    m = int(min(W, H) * 0.06)
    d.rectangle([m, m, W - m, H - m], outline=(255, 0, 120, 200), width=3)
    d.line([0, H * 0.5, W, H * 0.5], fill=(0, 220, 255, 120), width=2)
    d.line([W * 0.5, 0, W * 0.5, H], fill=(0, 220, 255, 120), width=2)
    # 右下角时长角标占位
    d.rectangle([W - m * 2.2, H - m * 1.15, W - m * 0.55, H - m * 0.55],
                outline=(255, 200, 0, 200), width=3)
    return Image.alpha_composite(img, layer)


# ---------------------------------------------------------------- 主流程

PLATFORM_SIZES = {
    "douyin": (1080, 1440), "xiaohongshu": (1080, 1440), "kuaishou": (1080, 1440),
    "shipinhao": (1080, 1440), "bilibili": (1920, 1080), "youtube": (1280, 720),
    "weibo": (1080, 1440), "generic_v": (1080, 1440), "generic_h": (1920, 1080),
}


def build(spec: dict, out_path: str | None = None, thumb_only: bool = False,
          safe: bool = False) -> dict:
    platform = spec.get("platform", "douyin")
    W, H = spec.get("size") or PLATFORM_SIZES.get(platform, (1080, 1440))
    W, H = int(W), int(H)

    bg = load_background({**spec, "_base_dir": spec.get("_base_dir", ".")}, W, H)
    img = apply_treatments(bg, spec.get("treatments", []) or [], W, H)

    stats = {"canvas": f"{W}x{H}", "platform": platform, "texts": []}

    for item in spec.get("shapes", []) or []:
        img = render_shapes(img, [item], W, H)

    for item in spec.get("texts", []) or []:
        lay = layout_block(item, W, H)
        bbox = text_bbox(item, lay, W, H)
        hl = item.get("highlight") or {}
        if hl and float(hl.get("opacity", 1.0)) >= 0.6:
            # 文字压在实心色块上，对比度要对着色块算，而不是对着背景
            bg_lum = luminance(parse_color(hl.get("color", "#FFD400"))[:3]) * 255
        else:
            bg_lum = mean_bg_luminance(img, bbox)
        bg_lum_color = (int(bg_lum), int(bg_lum), int(bg_lum))
        txt_color = parse_color(item.get("color", "#FFFFFF"))[:3]
        cr = contrast_ratio(bg_lum_color, txt_color)
        role = item.get("role", "body")
        stats["texts"].append({
            "role": role,
            "text": str(item.get("content", ""))[:30],
            "size_px": lay["size"],
            "size_pct_of_width": round(lay["size"] / W * 100, 1),
            "lines": len(lay["lines"]),
            "line_texts": lay["lines"],
            "block_px": [lay["block_w"], int(lay["block_h"])],
            "area_pct": round(lay["block_w"] * lay["block_h"] / (W * H) * 100, 1),
            "bg_mean_luminance": int(bg_lum),
            "contrast_ratio": round(cr, 2),
            "contrast_ok": cr >= 3.0,
        })
        img = render_text(img, item, lay, W, H)

    out_img = img.convert("RGB")
    if safe:
        out_img = safe_debug(out_img.convert("RGBA"), W, H).convert("RGB")

    out_path = out_path or (spec.get("output") or {}).get("path") or "cover.png"
    if not os.path.isabs(out_path):
        out_path = os.path.join(spec.get("_base_dir", "."), out_path)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    thumb_w = int((spec.get("output") or {}).get("preview_width", 220))
    thumb = out_img.copy()
    thumb.thumbnail((thumb_w, thumb_w * 3), Image.LANCZOS)
    thumb_path = f"{os.path.splitext(out_path)[0]}_thumb-{thumb.width}.jpg"
    thumb.save(thumb_path, quality=88)

    if not thumb_only:
        out_img.save(out_path, quality=95)
    stats["output"] = out_path if not thumb_only else None
    stats["thumb"] = thumb_path
    stats["thumb_width"] = thumb.width
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="视频封面合成器")
    ap.add_argument("spec", help="spec.json 路径")
    ap.add_argument("-o", "--out", help="输出图片路径")
    ap.add_argument("--thumb-only", action="store_true", help="只生成缩略预览")
    ap.add_argument("--safe-debug", action="store_true", help="叠加安全区参考线")
    args = ap.parse_args()

    with open(args.spec, "r", encoding="utf-8") as f:
        spec = json.load(f)
    spec["_base_dir"] = os.path.dirname(os.path.abspath(args.spec))

    stats = build(spec, args.out, args.thumb_only, args.safe_debug)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    W, H = (int(v) for v in stats["canvas"].split("x"))

    for t in stats["texts"]:
        if not t["contrast_ok"]:
            print(f"[warn] 对比度仅 {t['contrast_ratio']}（建议 ≥3.0，最好 ≥4.5）："
                  f"「{t['text']}」请加深阴影/换字色/补暗角渐变。", file=sys.stderr)
        if t["role"] == "title" and t["size_pct_of_width"] < 10:
            print(f"[warn] 主标题字号只占画宽的 {t['size_pct_of_width']}%，"
                  f"缩到信息流尺寸会糊：请放大到 ≥13%。", file=sys.stderr)
        if t["role"] != "title" and t["size_pct_of_width"] < 3.0:
            print(f"[warn] 辅助文字只有 {t['size_px']}px（占画宽 {t['size_pct_of_width']}%），"
                  f"手机上会看不清：建议 ≥ {int(round(W * 0.035))}px。", file=sys.stderr)
        if t["area_pct"] > 42:
            print(f"[warn] 文字覆盖 {t['area_pct']}%，画面过挤，建议删字或拆成主副标题。",
                  file=sys.stderr)

    # 主标题行数过多 → 缩略图里必糊
    titles = [t for t in stats["texts"] if t["role"] == "title"]
    if titles and titles[0]["lines"] > 3:
        print(f"[warn] 主标题 {titles[0]['lines']} 行，超过 3 行在信息流里读不完，"
              f"优先砍字而不是缩字号。", file=sys.stderr)


if __name__ == "__main__":
    main()
