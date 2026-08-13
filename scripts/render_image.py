#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_image.py — Westpac IQ Morning Report 16:9 レポート画像レンダラー（Pillow製・決定論的）v2

v2の変更（2026-08-13 ユーザーフィードバック反映）:
- ヘッダーを圧縮しカード領域を拡大（余白削減）
- 左テーマカードの文字を大型化＋枠内自動フィット（title/desc/impactすべて）
- 背景を上下グラデーションにして濃淡を付与、パネルとの明暗差を強調
- 方向感ラベルを方向色（上昇=緑/下落=水色/横ばい=白）で着色
- 折り返しで数値・英単語を途中分割しない（0.7062 が「0.706/2」に割れる問題の修正）

使い方:
  python scripts/render_image.py --data outputs/2026-08-13/report_data.json \
                                 --out  outputs/2026-08-13/report_image.png
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- 基本設定
W, H = 2560, 1440
BG_TOP  = (12, 27, 51)    # #0C1B33 上端（やや明るい紺）
BG_BOT  = (4, 8, 18)      # #040812 下端（ほぼ黒に近い紺）
PANEL   = "#0F1F3C"       # カード（背景より一段明るい紺＝濃淡）
GOLD    = "#C9A227"
GOLD_LT = "#E3B93B"
WHITE   = "#F5F5F7"
BODY    = "#DDE2EE"
GREEN   = "#4CAF50"
BLUE    = "#7EB3E8"
RED     = "#E05252"

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


def fit(kind: str, text: str, max_w: int, start: int, minimum: int) -> ImageFont.FreeTypeFont:
    """textがmax_wに収まる最大サイズのフォントを返す（start→minimumへ2pxずつ縮小）"""
    size = start
    while size > minimum and font(kind, size).getlength(text) > max_w:
        size -= 2
    return font(kind, size)


# ---------------------------------------------------------------- テキスト補助
KINSOKU = "。、．，！？）｝〕〉》」』】…‥ー"
_TOKEN_RE = re.compile(r"[0-9A-Za-z.%+\-,]+|.")


def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: int, max_lines: int) -> list:
    """トークン単位の折り返し（数値・英単語は途中で割らない）。行頭禁則はぶら下げ。"""
    lines = []
    for seg in str(text).split("\n"):
        cur = ""
        for tok in _TOKEN_RE.findall(seg):
            if f.getlength(cur + tok) <= max_w or (tok in KINSOKU and cur):
                cur += tok
            elif f.getlength(tok) > max_w:  # 1トークンが幅超過なら文字単位で分割
                for ch in tok:
                    if f.getlength(cur + ch) <= max_w or (ch in KINSOKU and cur):
                        cur += ch
                    else:
                        lines.append(cur)
                        cur = ch
            else:
                lines.append(cur)
                cur = tok
        lines.append(cur)
    lines = [l for l in lines if l != ""] or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and f.getlength(lines[-1] + "…") > max_w:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def draw_spaced(d, xy, text, f, fill, spacing=0, anchor_center_w=None):
    total = sum(f.getlength(c) for c in text) + spacing * max(0, len(text) - 1)
    x, y = xy
    if anchor_center_w is not None:
        x = x + (anchor_center_w - total) / 2
    for c in text:
        d.text((x, y), c, font=f, fill=fill)
        x += f.getlength(c) + spacing
    return total


# ---------------------------------------------------------------- 装飾
def gradient_bg() -> Image.Image:
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        c = tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)
    return img


def ornament_rule(d, y, x0=60, x1=W - 60):
    cx = (x0 + x1) // 2

    def diamond(x, r, fill=GOLD):
        d.polygon([(x, y - r), (x + r, y), (x, y + r), (x - r, y)], fill=fill)

    d.line([(x0 + 16, y), (cx - 110, y)], fill=GOLD, width=3)
    d.line([(cx + 110, y), (x1 - 16, y)], fill=GOLD, width=3)
    diamond(x0 + 6, 8)
    diamond(x1 - 6, 8)
    diamond(cx, 13, GOLD_LT)
    diamond(cx - 56, 7)
    diamond(cx + 56, 7)
    for sgn in (-1, 1):
        d.line([(cx + sgn * 94, y - 5), (cx + sgn * 66, y - 5)], fill=GOLD, width=2)
        d.line([(cx + sgn * 94, y + 5), (cx + sgn * 66, y + 5)], fill=GOLD, width=2)


# ---------------------------------------------------------------- アイコン（金地・背景色で抜き）
def draw_icon(d, cx, cy, kind, s=150):
    g, bg = GOLD_LT, "#0F1F3C"
    if kind == "oil":
        bw, bh = int(s * 0.68), int(s * 0.84)
        x0, y0 = cx - bw // 2, cy - bh // 2
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=int(s * 0.09), fill=g)
        for fy in (0.20, 0.80):
            yy = y0 + int(bh * fy)
            d.line([(x0 + 5, yy), (x0 + bw - 5, yy)], fill=bg, width=int(s * 0.04))
        dr = int(s * 0.115)
        dcy = cy + int(s * 0.03)
        d.polygon([(cx, dcy - int(s * 0.17)), (cx - dr, dcy + int(s * 0.04)), (cx + dr, dcy + int(s * 0.04))], fill=bg)
        d.ellipse([cx - dr, dcy - int(s * 0.06), cx + dr, dcy + int(s * 0.15)], fill=bg)
    elif kind == "market":
        r = int(s * 0.48)
        d.rounded_rectangle([cx - r, cy - r, cx + r, cy + r], radius=int(s * 0.10),
                            outline=g, width=int(s * 0.055))
        bw = int(s * 0.13)
        for fx, fh in [(0.30, 0.30), (0.50, 0.44), (0.70, 0.58)]:
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
        y0c, y1c = top + int(s * 0.32), cy + int(s * 0.30)
        cw = int(s * 0.10)
        for k in (-3, -1, 1, 3):
            x = cx + k * int(s * 0.135) - cw // 2
            d.rectangle([x, y0c, x + cw, y1c], fill=g)
        d.rectangle([cx - w2, y0c - int(s * 0.05), cx + w2, y0c], fill=g)
        d.rectangle([cx - w2 - int(s * 0.04), y1c, cx + w2 + int(s * 0.04), y1c + int(s * 0.07)], fill=g)
        d.rectangle([cx - w2 - int(s * 0.08), y1c + int(s * 0.07), cx + w2 + int(s * 0.08), y1c + int(s * 0.14)], fill=g)
    elif kind == "globe":
        r = int(s * 0.44)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=g, width=int(s * 0.05))
        d.ellipse([cx - int(r * 0.45), cy - r, cx + int(r * 0.45), cy + r], outline=g, width=int(s * 0.035))
        d.line([(cx - r, cy), (cx + r, cy)], fill=g, width=int(s * 0.035))
        d.arc([cx - r, cy - int(r * 1.55), cx + r, cy + int(r * 0.45)], 25, 155, fill=g, width=int(s * 0.035))
    elif kind == "percent":
        d.text((cx, cy), "%", font=font("serif_bold", int(s * 0.95)), fill=g, anchor="mm")
    else:
        r = int(s * 0.40)
        d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], outline=g, width=int(s * 0.05))
        d.polygon([(cx, cy - r // 2), (cx + r // 2, cy), (cx, cy + r // 2), (cx - r // 2, cy)], fill=g)


# ---------------------------------------------------------------- 矢印
def big_arrow(d, cx, cy, direction):
    if direction == "up":
        color, flip = GREEN, 1
    elif direction == "down":
        color, flip = BLUE, -1
    else:
        sw, sl, hw, hl = 48, 96, 116, 76
        d.rectangle([cx - (sl + hl) // 2, cy - sw // 2, cx + (sl + hl) // 2 - hl, cy + sw // 2], fill=WHITE)
        x0 = cx + (sl + hl) // 2 - hl
        d.polygon([(x0, cy - hw // 2), (x0, cy + hw // 2), (cx + (sl + hl) // 2, cy)], fill=WHITE)
        return
    sw, sl, hw, hl = 50, 100, 122, 80
    total = sl + hl
    tip_y = cy - flip * total // 2
    base_y = tip_y + flip * hl
    tail_y = cy + flip * total // 2
    d.polygon([(cx - hw // 2, base_y), (cx + hw // 2, base_y), (cx, tip_y)], fill=color)
    d.rectangle([cx - sw // 2, min(base_y, tail_y), cx + sw // 2, max(base_y, tail_y)], fill=color)


def impact_arrow_char(direction):
    return {"up": ("↑", GREEN), "down": ("↓", RED), "flat": ("→", GOLD_LT)}.get(direction, ("→", GOLD_LT))


def label_color(direction):
    return {"up": GREEN, "down": BLUE, "flat": WHITE}.get(direction, WHITE)


# ---------------------------------------------------------------- 描画本体
def render(data: dict, out_path: str):
    img = gradient_bg()
    d = ImageDraw.Draw(img)

    date = dt.date.fromisoformat(data["date_jst"])
    wd = "月火水木金土日"[date.weekday()]
    title = f"{date.year}年{date.month}月{date.day}日（{wd}）　Westpac IQ Morning Report"
    subtitle = data.get("subtitle", "本日の市場テーマと通貨ペア分析")

    # ヘッダー（圧縮版）
    ornament_rule(d, 36)
    d.text((W // 2, 116), title, font=font("serif_bold", 68), fill=WHITE, anchor="mm")
    draw_spaced(d, (0, 168), subtitle, font("serif_bold", 46), GOLD_LT, spacing=9, anchor_center_w=W)
    ornament_rule(d, 252)

    # レイアウト枠（カード領域を拡大）
    top, bottom, gap = 288, 1352, 24
    card_h = (bottom - top - 2 * gap) // 3
    lx0, lx1 = 50, 1238
    rx0, rx1 = 1322, 2510
    mid_x = 1280

    d.line([(mid_x, top), (mid_x, bottom)], fill=GOLD, width=2)
    my = (top + bottom) // 2
    d.polygon([(mid_x, my - 12), (mid_x + 9, my), (mid_x, my + 12), (mid_x - 9, my)], fill=GOLD_LT)

    # ---- 左：主要テーマ3件（枠幅を使い切るまで自動拡大）
    for i, th in enumerate(data["themes"][:3]):
        cy0 = top + i * (card_h + gap)
        cy1 = cy0 + card_h
        d.rounded_rectangle([lx0, cy0, lx1, cy1], radius=18, fill=PANEL, outline=GOLD, width=2)

        draw_icon(d, lx0 + 118, (cy0 + cy1) // 2, th.get("icon", "default"), s=152)
        d.line([(lx0 + 228, cy0 + 32), (lx0 + 228, cy1 - 32)], fill=GOLD, width=2)

        tx = lx0 + 262
        t_max_w = lx1 - 34 - tx

        # v3: 枠幅を使い切るまで自動拡大（上限あり・縦の収まりは影響行から自動調整）
        title = str(th.get("title", ""))
        t_size = 44
        while t_size < 74 and font("serif_bold", t_size + 2).getlength(title) <= t_max_w:
            t_size += 2
        f_title = font("serif_bold", t_size)
        d.text((tx, cy0 + 18), title, font=f_title, fill=WHITE)

        desc_lines = str(th.get("desc", "")).split("\n")[:2]
        d_size = 32
        while d_size < 46 and all(font("serif_reg", d_size + 2).getlength(l) <= t_max_w
                                  for l in desc_lines):
            d_size += 2
        f_desc = font("serif_reg", d_size)
        dy = cy0 + 24 + t_size + 16
        for ln in desc_lines:
            d.text((tx, dy), wrap(ln, f_desc, t_max_w, 1)[0], font=f_desc, fill=BODY)
            dy += int(d_size * 1.34)
        under_y = dy + 6
        d.line([(tx, under_y), (lx1 - 34, under_y)], fill=GOLD, width=2)

        imp_text = f"影響：{th.get('impact', '')} "
        i_size = 36
        while i_size < 52 and font("serif_bold", i_size + 2).getlength(imp_text + "↑") <= t_max_w:
            i_size += 2
        while i_size > 34 and under_y + 12 + int(i_size * 1.18) > cy1 - 12:
            i_size -= 2
        f_imp = font("serif_bold", i_size)
        iy = under_y + 12
        d.text((tx, iy), imp_text, font=f_imp, fill=GOLD_LT)
        ar, ac = impact_arrow_char(th.get("impact_dir", "flat"))
        d.text((tx + f_imp.getlength(imp_text) + 4, iy), ar, font=f_imp, fill=ac)

    # ---- 右：重要通貨ペア3件
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
        d.line([(rx0 + 388, cy0 + 32), (rx0 + 388, cy1 - 32)], fill=GOLD, width=2)

        direction = pr.get("dir", "flat")
        big_arrow(d, rx0 + 478, ccy, direction)

        tx = rx0 + 578
        bx0 = rx1 - 232
        text_w = bx0 - 24 - tx

        lab = str(pr.get("label", ""))
        l_size = 40
        while l_size < 66 and font("serif_bold", l_size + 2).getlength(lab) <= text_w:
            l_size += 2
        f_lab = font("serif_bold", l_size)
        d.text((tx, cy0 + 40), lab, font=f_lab, fill=label_color(direction))

        f_rsn = font("serif_reg", 34)
        ry = cy0 + 148
        for ln in wrap(pr.get("reason", ""), f_rsn, text_w, 3):
            d.text((tx, ry), ln, font=f_rsn, fill=BODY)
            ry += 48

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
    d.text((W - 60, H - 46), footer, font=font("serif_bold", 40), fill=GOLD_LT, anchor="rm")

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
