#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_image.py — Westpac IQ Morning Report 16:9 レポート画像レンダラー（Pillow製・決定論的）

ManusのAI画像生成（generate_image）の置き換え。毎日同一レイアウトで
report_data.json のテキストを差し込んで 2560x1440 PNG を生成する。

使い方:
  python scripts/render_image.py --data outputs/2026-08-12/report_data.json \
                                 --out  outputs/2026-08-12/report_image.png
"""
import argparse
import datetime as dt
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- 基本設定
W, H = 2560, 1440
BG      = "#0A1628"   # ダークネイビー背景
PANEL   = "#0C1930"   # カード内側（背景よりわずかに明るい紺）
GOLD    = "#C9A227"   # 金（罫線・見出し）
GOLD_LT = "#E3B93B"   # 金（明）
WHITE   = "#F5F5F7"
BODY    = "#DDE2EE"   # 本文（白に近いグレー）
GREEN   = "#4CAF50"   # 上矢印
BLUE    = "#7EB3E8"   # 下矢印（サンプル準拠の水色）
RED     = "#E05252"   # 下向き影響矢印用（強い下落表現）

FONT_CANDIDATES = {
    "serif_bold": [
        ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", 0),
        ("/usr/share/fonts/opentype/noto/NotoSerifCJKjp-Bold.otf", 0),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ],
    "serif_reg": [
        ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", 0),
        ("/usr/share/fonts/opentype/noto/NotoSerifCJKjp-Regular.otf", 0),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ],
}
_font_cache = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key in _font_cache:
        return _font_cache[key]
    last_err = None
    for path, idx in FONT_CANDIDATES[kind]:
        if os.path.exists(path):
            try:
                f = ImageFont.truetype(path, size, index=idx)
                _font_cache[key] = f
                return f
            except Exception as e:  # pragma: no cover
                last_err = e
    raise RuntimeError(f"日本語フォントが見つかりません（fonts-noto-cjk-extra を導入してください）: {last_err}")


# ---------------------------------------------------------------- テキスト補助
KINSOKU = "。、．，！？）｝〕〉》」』】…‥ー"


def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: int, max_lines: int) -> list:
    """文字単位の折り返し（日本語向け・行頭禁則はぶら下げ）。既存の改行は尊重。"""
    lines = []
    for seg in str(text).split("\n"):
        cur = ""
        for ch in seg:
            if f.getlength(cur + ch) <= max_w or (ch in KINSOKU and cur):
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    lines = [l for l in lines if l != ""] or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and f.getlength(lines[-1] + "…") > max_w:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def draw_spaced(d: ImageDraw.ImageDraw, xy, text, f, fill, spacing=0, anchor_center_w=None):
    """字間を空けて描画。anchor_center_w を渡すとその幅の中でセンタリング。"""
    total = sum(f.getlength(c) for c in text) + spacing * max(0, len(text) - 1)
    x, y = xy
    if anchor_center_w is not None:
        x = x + (anchor_center_w - total) / 2
    for c in text:
        d.text((x, y), c, font=f, fill=fill)
        x += f.getlength(c) + spacing
    return total


# ---------------------------------------------------------------- 装飾
def ornament_rule(d: ImageDraw.ImageDraw, y: int, x0: int = 60, x1: int = W - 60):
    cx = (x0 + x1) // 2

    def diamond(x, r, fill=GOLD):
        d.polygon([(x, y - r), (x + r, y), (x, y + r), (x - r, y)], fill=fill)

    d.line([(x0 + 18, y), (cx - 120, y)], fill=GOLD, width=3)
    d.line([(cx + 120, y), (x1 - 18, y)], fill=GOLD, width=3)
    diamond(x0 + 8, 9)
    diamond(x1 - 8, 9)
    diamond(cx, 14, GOLD_LT)
    diamond(cx - 60, 8)
    diamond(cx + 60, 8)
    d.line([(cx - 100, y - 5), (cx - 70, y - 5)], fill=GOLD, width=2)
    d.line([(cx + 70, y - 5), (cx + 100, y - 5)], fill=GOLD, width=2)
    d.line([(cx - 100, y + 5), (cx - 70, y + 5)], fill=GOLD, width=2)
    d.line([(cx + 70, y + 5), (cx + 100, y + 5)], fill=GOLD, width=2)


# ---------------------------------------------------------------- アイコン（金地・背景色で抜き）
def draw_icon(d: ImageDraw.ImageDraw, cx: int, cy: int, kind: str, s: int = 170):
    g, bg = GOLD_LT, BG
    if kind == "oil":
        bw, bh = int(s * 0.66), int(s * 0.80)
        x0, y0 = cx - bw // 2, cy - bh // 2
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=int(s * 0.08), fill=g)
        for fy in (0.22, 0.5, 0.78):
            yy = y0 + int(bh * fy)
            d.line([(x0 + 6, yy), (x0 + bw - 6, yy)], fill=bg, width=int(s * 0.045))
        d.ellipse([x0 + 8, y0 + 4, x0 + bw - 8, y0 + int(s * 0.14)], outline=bg, width=int(s * 0.035))
        dr = int(s * 0.10)
        d.polygon([(cx, cy - int(s * 0.02)), (cx - dr, cy + int(s * 0.16)), (cx + dr, cy + int(s * 0.16))], fill=bg)
        d.ellipse([cx - dr, cy + int(s * 0.08), cx + dr, cy + int(s * 0.26)], fill=bg)
    elif kind == "market":
        r = int(s * 0.48)
        d.rounded_rectangle([cx - r, cy - r, cx + r, cy + r], radius=int(s * 0.10),
                            outline=g, width=int(s * 0.055))
        bars = [(0.30, 0.30), (0.50, 0.44), (0.70, 0.58)]
        bw = int(s * 0.13)
        for fx, fh in bars:
            bx = cx - r + int(2 * r * fx) - bw // 2
            hh = int(2 * r * fh * 0.62)
            d.rectangle([bx, cy + r - int(s * 0.10) - hh, bx + bw, cy + r - int(s * 0.10)], fill=g)
        p0 = (cx - r + int(s * 0.14), cy + int(s * 0.10))
        p1 = (cx, cy - int(s * 0.06))
        p2 = (cx + r - int(s * 0.20), cy - int(s * 0.26))
        d.line([p0, p1, p2], fill=g, width=int(s * 0.05))
        ah = int(s * 0.12)
        d.polygon([(p2[0] + ah, p2[1] - ah), (p2[0] - int(ah * 1.1), p2[1]),
                   (p2[0], p2[1] + int(ah * 1.1))], fill=g)
    elif kind == "bank":
        w2 = int(s * 0.52)
        top = cy - int(s * 0.46)
        d.polygon([(cx, top), (cx - w2, top + int(s * 0.26)), (cx + w2, top + int(s * 0.26))],
                  outline=g, width=int(s * 0.045))
        d.ellipse([cx - int(s * 0.05), top + int(s * 0.10), cx + int(s * 0.05), top + int(s * 0.20)], fill=g)
        cols_y0 = top + int(s * 0.32)
        cols_y1 = cy + int(s * 0.30)
        cw = int(s * 0.10)
        for k in (-3, -1, 1, 3):
            x = cx + k * int(s * 0.135) - cw // 2
            d.rectangle([x, cols_y0, x + cw, cols_y1], fill=g)
        d.rectangle([cx - w2, cols_y0 - int(s * 0.05), cx + w2, cols_y0], fill=g)
        d.rectangle([cx - w2 - int(s * 0.04), cols_y1, cx + w2 + int(s * 0.04), cols_y1 + int(s * 0.07)], fill=g)
        d.rectangle([cx - w2 - int(s * 0.08), cols_y1 + int(s * 0.07), cx + w2 + int(s * 0.08), cols_y1 + int(s * 0.14)], fill=g)
    elif kind == "globe":
        r = int(s * 0.44)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=g, width=int(s * 0.05))
        d.ellipse([cx - int(r * 0.45), cy - r, cx + int(r * 0.45), cy + r], outline=g, width=int(s * 0.035))
        d.line([(cx - r, cy), (cx + r, cy)], fill=g, width=int(s * 0.035))
        d.arc([cx - r, cy - int(r * 1.55), cx + r, cy + int(r * 0.45)], 25, 155, fill=g, width=int(s * 0.035))
    elif kind == "percent":
        f = font("serif_bold", int(s * 0.95))
        d.text((cx, cy), "%", font=f, fill=g, anchor="mm")
    else:  # default: ダイヤ
        r = int(s * 0.40)
        d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], outline=g, width=int(s * 0.05))
        d.polygon([(cx, cy - r // 2), (cx + r // 2, cy), (cx, cy + r // 2), (cx - r // 2, cy)], fill=g)


# ---------------------------------------------------------------- 矢印
def big_arrow(d: ImageDraw.ImageDraw, cx: int, cy: int, direction: str):
    if direction == "up":
        color, flip = GREEN, 1
    elif direction == "down":
        color, flip = BLUE, -1
    else:  # flat
        sw, sl, hw, hl = 46, 92, 112, 74
        d.rectangle([cx - (sl + hl) // 2, cy - sw // 2, cx + (sl + hl) // 2 - hl, cy + sw // 2], fill=WHITE)
        x0 = cx + (sl + hl) // 2 - hl
        d.polygon([(x0, cy - hw // 2), (x0, cy + hw // 2), (cx + (sl + hl) // 2, cy)], fill=WHITE)
        return
    sw, sl, hw, hl = 48, 96, 118, 78   # 軸幅・軸長・頭幅・頭長
    total = sl + hl
    tip_y = cy - flip * total // 2
    base_y = tip_y + flip * hl
    tail_y = cy + flip * total // 2
    d.polygon([(cx - hw // 2, base_y), (cx + hw // 2, base_y), (cx, tip_y)], fill=color)
    d.rectangle([cx - sw // 2, min(base_y, tail_y), cx + sw // 2, max(base_y, tail_y)], fill=color)


def impact_arrow_char(direction: str):
    return {"up": ("↑", GREEN), "down": ("↓", RED), "flat": ("→", GOLD_LT)}.get(direction, ("→", GOLD_LT))


# ---------------------------------------------------------------- 描画本体
def render(data: dict, out_path: str):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    date = dt.date.fromisoformat(data["date_jst"])
    wd = "月火水木金土日"[date.weekday()]
    title = f"{date.year}年{date.month}月{date.day}日（{wd}）　Westpac IQ Morning Report"
    subtitle = data.get("subtitle", "本日の市場テーマと通貨ペア分析")

    # ヘッダー
    ornament_rule(d, 44)
    d.text((W // 2, 152), title, font=font("serif_bold", 80), fill=WHITE, anchor="mm")
    draw_spaced(d, (0, 212), subtitle, font("serif_bold", 56), WHITE, spacing=10, anchor_center_w=W)
    ornament_rule(d, 312)

    # レイアウト枠
    top, bottom, gap = 352, 1330, 26
    card_h = (bottom - top - 2 * gap) // 3
    lx0, lx1 = 50, 1238
    rx0, rx1 = 1322, 2510
    mid_x = 1280

    d.line([(mid_x, top), (mid_x, bottom)], fill=GOLD, width=2)
    my = (top + bottom) // 2
    d.polygon([(mid_x, my - 12), (mid_x + 9, my), (mid_x, my + 12), (mid_x - 9, my)], fill=GOLD_LT)

    # ---- 左：主要テーマ3件
    for i, th in enumerate(data["themes"][:3]):
        cy0 = top + i * (card_h + gap)
        cy1 = cy0 + card_h
        d.rounded_rectangle([lx0, cy0, lx1, cy1], radius=18, fill=PANEL, outline=GOLD, width=2)

        icon_cx, icon_cy = lx0 + 150, (cy0 + cy1) // 2
        draw_icon(d, icon_cx, icon_cy, th.get("icon", "default"), s=176)
        d.line([(lx0 + 292, cy0 + 34), (lx0 + 292, cy1 - 34)], fill=GOLD, width=2)

        tx = lx0 + 330
        t_max_w = lx1 - 36 - tx
        f_title = font("serif_bold", 52)
        title_lines = wrap(th.get("title", ""), f_title, t_max_w, 1)
        d.text((tx, cy0 + 32), title_lines[0], font=f_title, fill=WHITE)

        f_desc = font("serif_reg", 36)
        desc_lines = wrap(th.get("desc", ""), f_desc, t_max_w, 2)
        dy = cy0 + 108
        for ln in desc_lines:
            d.text((tx, dy), ln, font=f_desc, fill=BODY)
            dy += 50
        under_y = cy0 + 216
        d.line([(tx, under_y), (tx + int(t_max_w * 0.72), under_y)], fill=GOLD, width=2)

        f_imp = font("serif_bold", 42)
        imp_text = f"影響：{th.get('impact', '')} "
        d.text((tx, under_y + 14), imp_text, font=f_imp, fill=GOLD_LT)
        ar, ac = impact_arrow_char(th.get("impact_dir", "flat"))
        d.text((tx + f_imp.getlength(imp_text) + 4, under_y + 14), ar, font=f_imp, fill=ac)

    # ---- 右：重要通貨ペア3件
    # ペア名は縦線（rx0+388）の手前に必ず収まるよう、3カード共通のサイズへ自動調整
    ALL_PAIRS = ["USD/JPY", "AUD/USD", "XAU/USD", "EUR/USD", "GBP/USD"]
    fit_targets = ALL_PAIRS + [str(p.get("pair", "")) for p in data["pairs_image"][:3]]
    pair_x = rx0 + 26
    max_pair_w = (rx0 + 388) - pair_x - 18
    pair_size = 78
    while pair_size > 50 and any(
            font("serif_bold", pair_size).getlength(t) > max_pair_w for t in fit_targets):
        pair_size -= 2
    f_pair = font("serif_bold", pair_size)

    for i, pr in enumerate(data["pairs_image"][:3]):
        cy0 = top + i * (card_h + gap)
        cy1 = cy0 + card_h
        ccy = (cy0 + cy1) // 2
        d.rounded_rectangle([rx0, cy0, rx1, cy1], radius=18, fill=PANEL, outline=GOLD, width=2)

        d.text((pair_x, ccy), pr.get("pair", ""), font=f_pair, fill=WHITE, anchor="lm")
        d.line([(rx0 + 388, cy0 + 34), (rx0 + 388, cy1 - 34)], fill=GOLD, width=2)

        big_arrow(d, rx0 + 478, ccy, pr.get("dir", "flat"))

        tx = rx0 + 578
        bx0 = rx1 - 232                       # バッジ左端
        text_w = bx0 - 24 - tx                # バッジ手前までの折返し幅
        lab = str(pr.get("label", ""))
        lab_size = 54
        while lab_size > 40 and font("serif_bold", lab_size).getlength(lab) > text_w:
            lab_size -= 2
        f_lab = font("serif_bold", lab_size)
        d.text((tx, cy0 + 42), wrap(lab, f_lab, text_w, 1)[0], font=f_lab, fill=WHITE)
        f_rsn = font("serif_reg", 32)
        ry = cy0 + 134
        for ln in wrap(pr.get("reason", ""), f_rsn, text_w, 3):
            d.text((tx, ry), ln, font=f_rsn, fill=BODY)
            ry += 45

        # バッジ（金二重枠・自動縮小）
        bx1 = rx1 - 26
        bh = 150
        by0, by1 = ccy - bh // 2, ccy + bh // 2
        d.rounded_rectangle([bx0, by0, bx1, by1], radius=12, outline=GOLD, width=3)
        d.rounded_rectangle([bx0 + 7, by0 + 7, bx1 - 7, by1 - 7], radius=8, outline=GOLD, width=1)
        words = str(pr.get("badge", "")).split()
        blines = [" ".join(words)] if len(words) <= 1 else [
            " ".join(words[: max(1, len(words) // 2)]),
            " ".join(words[max(1, len(words) // 2):]),
        ]
        inner_w = (bx1 - bx0) - 34
        size = 36
        while size > 24:
            fb = font("serif_bold", size)
            if all(fb.getlength(l) <= inner_w for l in blines):
                break
            size -= 2
        f_bdg = font("serif_bold", size)
        bcx = (bx0 + bx1) // 2
        if len(blines) == 1:
            d.text((bcx, ccy), blines[0], font=f_bdg, fill=GOLD_LT, anchor="mm")
        else:
            d.text((bcx, ccy - 25), blines[0], font=f_bdg, fill=GOLD_LT, anchor="mm")
            d.text((bcx, ccy + 25), blines[1], font=f_bdg, fill=GOLD_LT, anchor="mm")

    # フッター（出典）
    src = data.get("source_label", "Westpac IQ Morning Report")
    footer = f"出典: {src} {date.strftime('%Y/%m/%d')}"
    d.text((W - 60, H - 52), footer, font=font("serif_bold", 40), fill=GOLD_LT, anchor="rm")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG")
    print(f"[render_image] saved: {out_path} ({W}x{H})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="report_data.json のパス")
    ap.add_argument("--out", required=True, help="出力PNGパス")
    args = ap.parse_args()
    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)
    render(data, args.out)


if __name__ == "__main__":
    sys.exit(main())
