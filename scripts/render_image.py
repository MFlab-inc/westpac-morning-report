#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_image.py — Westpac IQ Morning Report 16:9 レポート画像レンダラー（Pillow製・決定論的）v3

v3（2026-11-20 リニューアル「案A2」）:
- 明朝体 → 太いゴシック体（Noto Sans CJK JP の Black／Bold／Medium）。
  スマホのタイムラインでは画像が約1/4以下に縮むため、細い線・小さい文字をやめる
- 構成を「要点だけ」に絞る:
    ヘッダー（日付・朝の為替市況）
    大見出し（report_data.headline。金のグラデーション・極太）
    補足2行（themes[0].desc）＋ 赤い注目バッジ（report_data.alert）
    数値ボックス3つ（pairs_image の3ペア。レートと変化率は原文の表から読み取る）
    そのほかの要点2つ（themes[1]・themes[2] のタイトルと影響）
    フッター（出典・数値の出所）
- レートと変化率はAIの出力を使わず、原文（sources/<date>/westpac.txt）の表から
  プログラムが直接読み取る。表に数値がないペア（例: GBP/USD）は方向ラベルを大きく表示する
- headline／alert が無い場合は、themes[0].title を見出しにし、バッジを描かない
  （検証ゲートG12がFAILにする）

使い方:
  python scripts/render_image.py --data outputs/2026-11-20/report_data.json \\
                                 --out  outputs/2026-11-20/report_image.png \\
                                 [--source sources/2026-11-20/westpac.txt]
  --source を省略した場合は sources/<date_jst>/westpac.txt を探す。
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
M = 110                       # 左右の余白
BG_TOP = (11, 26, 51)         # 背景グラデーション上端（紺）
BG_BOT = (4, 9, 20)           # 下端（ほぼ黒に近い紺）
PANEL = (16, 33, 63)          # ボックス
EDGE = (40, 62, 100)          # ボックスの枠線
GOLD = (232, 185, 49)
GOLD_HI, GOLD_LO = (255, 224, 130), (214, 158, 28)   # 見出しの金グラデーション
WHITE = (255, 255, 255)
SUB = (196, 207, 226)         # 補助テキスト
MUTED = (140, 156, 186)       # 注記
UP = (52, 209, 122)           # 上昇＝緑
DOWN = (90, 169, 255)         # 下落＝青
FLAT = (230, 234, 242)        # 横ばい＝白
ALERT = (226, 46, 46)         # 注目バッジ＝赤（バッジ以外には使わない）

HEADLINE_FONT_MAX = 168
ALERT_TOP_LABEL = "注目"
FOOTER_NOTE = "数値・変化率は Westpac IQ 掲載値"
NO_RATE_NOTE = "レートは原文の表に掲載なし"

# 原文の表の行ラベル（表に無いペアは載せない）
TABLE_LABEL = {"USD/JPY": "USD/JPY", "AUD/USD": "AUD/USD", "EUR/USD": "EUR/USD",
               "XAU/USD": "Gold"}
JP_NAME = {"USD/JPY": "ドル円", "AUD/USD": "豪ドル", "EUR/USD": "ユーロドル",
           "XAU/USD": "金", "GBP/USD": "ポンドドル"}

# ---------------------------------------------------------------- フォント
FONT_DIRS = ["/usr/share/fonts/opentype/noto", "/usr/share/fonts/truetype/noto",
             "/usr/share/fonts/noto-cjk", "/usr/share/fonts/opentype/noto-cjk"]
FONT_FILES = {
    # fonts-noto-cjk-extra が無い環境では Bold／Regular に落とす
    "black": ["NotoSansCJK-Black.ttc", "NotoSansCJKjp-Black.otf",
              "NotoSansCJK-Bold.ttc", "NotoSansCJKjp-Bold.otf"],
    "bold": ["NotoSansCJK-Bold.ttc", "NotoSansCJKjp-Bold.otf"],
    "medium": ["NotoSansCJK-Medium.ttc", "NotoSansCJKjp-Medium.otf",
               "NotoSansCJK-Regular.ttc", "NotoSansCJKjp-Regular.otf",
               "NotoSansCJK-Bold.ttc"],
}
_font_cache = {}
_face_index_cache = {}


def _jp_face_index(path: str) -> int:
    """.ttc の中から日本語（JP）の書体番号を探す。見つからなければ0"""
    if path in _face_index_cache:
        return _face_index_cache[path]
    idx = 0
    if path.endswith(".ttc"):
        for i in range(10):
            try:
                fam = ImageFont.truetype(path, 12, index=i).getname()[0]
            except Exception:
                break
            if fam.endswith(" JP"):
                idx = i
                break
    _face_index_cache[path] = idx
    return idx


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key in _font_cache:
        return _font_cache[key]
    for name in FONT_FILES[kind]:
        for d in FONT_DIRS:
            path = os.path.join(d, name)
            if os.path.exists(path):
                f = ImageFont.truetype(path, size, index=_jp_face_index(path))
                _font_cache[key] = f
                return f
    raise RuntimeError("日本語フォント（Noto Sans CJK）が見つかりません。"
                       "fonts-noto-cjk と fonts-noto-cjk-extra を導入してください")


def fit(kind: str, text: str, max_w: float, start: int, minimum: int) -> ImageFont.FreeTypeFont:
    """textがmax_wに収まる最大サイズ（start→minimumへ2pxずつ縮小）。minimumでも収まらなければminimum"""
    size = start
    while size > minimum and font(kind, size).getlength(text) > max_w:
        size -= 2
    return font(kind, size)


def ellipsize(text: str, f: ImageFont.FreeTypeFont, max_w: float) -> str:
    """幅に収まらなければ末尾を「…」で省略する（最後の安全策）"""
    if f.getlength(text) <= max_w:
        return text
    while text and f.getlength(text + "…") > max_w:
        text = text[:-1]
    return text + "…"


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


def split_two_lines(text: str, f: ImageFont.FreeTypeFont, max_w: int) -> list:
    """1行に収まらない見出しを、中央に近い助詞（で・に・が・を・、）の直後で2行に分ける。
    適当な位置が無ければトークン単位の折り返し（最大2行・超過は「…」）"""
    if f.getlength(text) <= max_w:
        return [text]
    cands = [i + 1 for i, ch in enumerate(text) if ch in "でにがを、" and 0 < i < len(text) - 2]
    cands = [i for i in cands if f.getlength(text[:i]) <= max_w and f.getlength(text[i:]) <= max_w]
    if cands:
        i = min(cands, key=lambda k: abs(k - len(text) / 2))
        return [text[:i], text[i:]]
    return wrap(text, f, max_w, 2)


# ---------------------------------------------------------------- 原文の表
def table_quote(src_text: str, pair: str):
    """原文の表の「LABEL 値 変化%」の行から (値の文字列, 変化率の文字列) を返す。
    表に無いペア・行が見つからない場合は None。値・変化率は原文の表記のまま使い、
    丸め直さない（金の値だけ桁区切りのカンマを補う）。"""
    label = TABLE_LABEL.get(pair)
    if not label or not src_text:
        return None
    m = re.search(rf"\b{re.escape(label)}\s+([\d,]+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)%", src_text)
    if not m:
        return None
    value, pct = m.group(1), m.group(2)
    if "," not in value:
        ip, _, dp = value.partition(".")
        if len(ip) >= 4:
            value = f"{int(ip):,}" + (f".{dp}" if dp else "")
    return value, pct


def pct_direction(pct: str) -> str:
    v = float(pct)
    return "up" if v > 0 else "down" if v < 0 else "flat"


def dir_color(direction: str):
    return {"up": UP, "down": DOWN}.get(direction, FLAT)


# ---------------------------------------------------------------- 装飾
def gradient_bg() -> Image.Image:
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        c = tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)
    return img


def gradient_text(img: Image.Image, x: int, baseline: int, text: str, f: ImageFont.FreeTypeFont):
    """金の縦グラデーションで文字を描く（baseline＝文字のベースライン位置）"""
    l, t, r, b = f.getbbox(text)
    mask = Image.new("L", (max(1, r), max(1, b)), 0)
    ImageDraw.Draw(mask).text((0, 0), text, font=f, fill=255)
    grad = Image.new("RGB", mask.size)
    gd = ImageDraw.Draw(grad)
    for yy in range(mask.size[1]):
        k = max(0, yy - t) / max(1, b - t)
        gd.line([(0, yy), (mask.size[0], yy)],
                fill=tuple(int(GOLD_HI[i] + (GOLD_LO[i] - GOLD_HI[i]) * k) for i in range(3)))
    img.paste(grad, (x, baseline - f.getmetrics()[0]), mask)


def triangle(d, x, cy, size, direction, color):
    """▲▼▶ を図形で描く（フォントの字形より輪郭がくっきりする）"""
    h = size
    if direction == "up":
        d.polygon([(x, cy + h * 0.45), (x + h, cy + h * 0.45), (x + h / 2, cy - h * 0.45)], fill=color)
    elif direction == "down":
        d.polygon([(x, cy - h * 0.45), (x + h, cy - h * 0.45), (x + h / 2, cy + h * 0.45)], fill=color)
    else:
        d.polygon([(x + h * 0.1, cy - h * 0.45), (x + h * 0.1, cy + h * 0.45), (x + h * 0.95, cy)],
                  fill=color)


def alert_badge(img: Image.Image, right_x: int, top_y: int, text: str, angle: float = -4):
    """赤い斜めの注目バッジ。右端right_x・上端top_yに置き、(幅, 高さ)を返す"""
    f1 = font("bold", 36)
    f2 = fit("black", text, 760 - 90, 58, 40)
    text = ellipsize(text, f2, 760 - 90)
    w = int(max(f1.getlength(ALERT_TOP_LABEL), f2.getlength(text))) + 90
    h = 168
    b = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(b)
    bd.rounded_rectangle([0, 0, w - 1, h - 1], radius=18, fill=ALERT + (255,))
    bd.rounded_rectangle([10, 10, w - 11, h - 11], radius=12, outline=(255, 255, 255, 230), width=4)
    bd.text((w / 2, 46), ALERT_TOP_LABEL, font=f1, fill=WHITE, anchor="mm")
    bd.text((w / 2, 110), text, font=f2, fill=WHITE, anchor="mm")
    rb = b.rotate(angle, resample=Image.BICUBIC, expand=True)
    img.paste(rb, (right_x - rb.width, top_y), rb)
    return rb.width, rb.height


# ---------------------------------------------------------------- アイコン（金地・背景色で抜き）
def draw_icon(d, cx, cy, kind, s=150):
    g, bg = GOLD, PANEL
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
        d.text((cx, cy), "%", font=font("black", int(s * 0.95)), fill=g, anchor="mm")
    else:
        r = int(s * 0.40)
        d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], outline=g, width=int(s * 0.05))
        d.polygon([(cx, cy - r // 2), (cx + r // 2, cy), (cx, cy + r // 2), (cx - r // 2, cy)], fill=g)


def theme_icons(themes: list) -> list:
    """3テーマのアイコンを重複しないように決める（プロンプト違反で重複した場合の保険）"""
    fallback = ["market", "bank", "globe", "oil", "percent", "default"]
    used, out = set(), []
    for th in themes:
        ic = str(th.get("icon", "default"))
        if ic in used:
            ic = next((c for c in fallback if c not in used), "default")
        used.add(ic)
        out.append(ic)
    return out


# ---------------------------------------------------------------- 描画本体
def render(data: dict, out_path: str, src_text: str = None):
    img = gradient_bg()
    d = ImageDraw.Draw(img)

    date = dt.date.fromisoformat(data["date_jst"])
    wd = "月火水木金土日"[date.weekday()]
    src_label = data.get("source_label", "Westpac IQ Morning Report")
    themes = list(data.get("themes", []))[:3]
    while len(themes) < 3:
        themes.append({"title": "", "desc": "", "impact": "", "impact_dir": "flat"})
    icons = theme_icons(themes)

    # ---- ヘッダー
    f_head = font("black", 62)
    date_txt = f"{date.month}/{date.day}（{wd}）"
    d.text((M, 136), date_txt, font=f_head, fill=GOLD, anchor="ls")
    d.text((M + f_head.getlength(date_txt) + 26, 136), "朝の為替市況", font=f_head, fill=WHITE, anchor="ls")
    d.text((W - M, 132), src_label, font=font("bold", 40), fill=SUB, anchor="rs")
    d.rectangle([M, 168, W - M, 172], fill=GOLD)

    # ---- 大見出し（headline。無ければテーマ1のタイトル）
    headline = str(data.get("headline") or themes[0].get("title", "")).strip()
    fh = fit("black", headline, W - 2 * M, HEADLINE_FONT_MAX, 96)
    gradient_text(img, M, 360, ellipsize(headline, fh, W - 2 * M), fh)

    # ---- 注目バッジ（alert。無ければ描かない）＋補足2行（テーマ1の説明）
    alert = str(data.get("alert") or "").strip()
    bw = 0
    if alert:
        bw, _ = alert_badge(img, W - M + 6, 392, alert)
    sub_w = W - 2 * M - (bw + 40 if bw else 0)
    sub_lines = [l.strip() for l in str(themes[0].get("desc", "")).split("\n") if l.strip()][:2]
    if sub_lines:
        fs = font("bold", 52)
        for l in sub_lines:
            fs = min(fs, fit("bold", l, sub_w, 52, 40), key=lambda f: f.size)
        for i, l in enumerate(sub_lines):
            d.text((M, 464 + i * 68), ellipsize(l, fs, sub_w), font=fs, fill=WHITE, anchor="ls")

    # ---- 数値ボックス3つ（その日の主役ペア）
    top, bh, gap = 640, 360, 40
    bw3 = (W - 2 * M - gap * 2) // 3
    for i, pr in enumerate(list(data.get("pairs_image", []))[:3]):
        pair = str(pr.get("pair", ""))
        x0 = M + i * (bw3 + gap)
        quote = table_quote(src_text, pair)
        direction = pct_direction(quote[1]) if quote else str(pr.get("dir", "flat"))
        c = dir_color(direction)
        d.rounded_rectangle([x0, top, x0 + bw3, top + bh], radius=22, fill=PANEL, outline=EDGE, width=2)
        d.rounded_rectangle([x0, top, x0 + bw3, top + 14], radius=7, fill=c)
        d.text((x0 + 44, top + 92), JP_NAME.get(pair, pair), font=font("bold", 56), fill=WHITE, anchor="ls")
        d.text((x0 + bw3 - 44, top + 90), pair, font=font("medium", 38), fill=MUTED, anchor="rs")
        label = str(pr.get("label", ""))
        if quote:
            value, pct = quote
            d.text((x0 + 44, top + 238), value, font=fit("black", value, bw3 - 88, 150, 90),
                   fill=WHITE, anchor="ls")
            triangle(d, x0 + 46, top + 300, 48, direction, c)
            pct_txt = f"{pct.lstrip('+-')}%"
            f_pct = font("black", 72)
            d.text((x0 + 110, top + 326), pct_txt, font=f_pct, fill=c, anchor="ls")
            lab_w = bw3 - 44 - (110 + f_pct.getlength(pct_txt) + 30)
            f_lab = fit("bold", label, lab_w, 60, 36)
            d.text((x0 + bw3 - 44, top + 324), ellipsize(label, f_lab, lab_w), font=f_lab,
                   fill=c, anchor="rs")
        else:  # 表に数値が無いペアは方向ラベルを大きく表示
            triangle(d, x0 + 46, top + 190, 80, direction, c)
            lab_w = bw3 - 150 - 44
            f_lab = fit("black", label, lab_w, 96, 56)
            d.text((x0 + 150, top + 190), ellipsize(label, f_lab, lab_w), font=f_lab, fill=c, anchor="lm")
            d.text((x0 + 46, top + 300), NO_RATE_NOTE, font=font("medium", 34), fill=MUTED, anchor="lm")

    # ---- そのほかの要点（テーマ2・3）
    ty = top + bh + 28
    d.text((M, ty), "そのほかの要点", font=font("bold", 40), fill=GOLD)
    cy0 = ty + 58
    ch, cg = 1330 - cy0, 40
    cw = (W - 2 * M - cg) // 2
    for i, th in enumerate(themes[1:3]):
        x0 = M + i * (cw + cg)
        d.rounded_rectangle([x0, cy0, x0 + cw, cy0 + ch], radius=20, fill=PANEL, outline=EDGE, width=2)
        draw_icon(d, x0 + 120, cy0 + ch // 2, icons[i + 1], s=min(130, ch - 70))
        tx, tw = x0 + 240, cw - 290
        title = str(th.get("title", ""))
        ft = fit("black", title, tw, 58, 50)
        if ft.getlength(title) <= tw:
            lines, i_size = [title], 46
        else:
            ft = font("black", 52)
            lines, i_size = split_two_lines(title, ft, tw), 44
        lh = int(ft.size * 1.3)
        block = lh * len(lines) + 24 + i_size
        yy = cy0 + (ch - block) // 2 - 8
        for ln in lines:
            d.text((tx, yy), ln, font=ft, fill=WHITE)
            yy += lh
        arr = {"up": "↑", "down": "↓"}.get(th.get("impact_dir"), "→")
        imp = f"影響：{th.get('impact', '')} {arr}"
        f_imp = fit("bold", imp, tw, i_size, 34)
        d.text((tx, yy + 24), ellipsize(imp, f_imp, tw), font=f_imp, fill=GOLD)

    # ---- フッター
    d.rectangle([M, 1352, W - M, 1354], fill=EDGE)
    f_ft = font("medium", 34)
    d.text((M, 1372), f"出典: {src_label} {date.strftime('%Y/%m/%d')}", font=f_ft, fill=MUTED)
    d.text((W - M - f_ft.getlength(FOOTER_NOTE), 1372), FOOTER_NOTE, font=f_ft, fill=MUTED)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG")
    print(f"[render_image] saved: {out_path} ({W}x{H})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="report_data.json のパス")
    ap.add_argument("--out", required=True, help="出力PNGパス")
    ap.add_argument("--source", default=None,
                    help="原文テキスト（westpac.txt）のパス。省略時は sources/<date_jst>/westpac.txt")
    args = ap.parse_args()
    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)
    src_path = args.source or os.path.join("sources", str(data.get("date_jst", "")), "westpac.txt")
    src_text = None
    if os.path.exists(src_path):
        with open(src_path, encoding="utf-8") as f:
            src_text = f.read()
    else:
        print(f"[render_image] 原文テキストなし（{src_path}）: 数値ボックスは方向ラベルのみ表示")
    render(data, args.out, src_text)


if __name__ == "__main__":
    sys.exit(main())
