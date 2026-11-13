#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_report.py — 納品前の機械検証ゲート。結果は outputs/<date>/audit.json に保存。

ゲート:
  G1 日付整合 / G2 暗号通貨語の混入ゼロ / G3 対象5ペア限定 / G4 プレースホルダ残存なし
  G5 出典表記 / G6 規定ハッシュタグ / G7 投稿にURLなし / G8 数値のPDF原文照合（liveのみ）
  G9 イベント時刻JST換算チェック（原文時刻をzoneinfoベースの正しい時差で換算した
     結果と本文イベント表が一致するか。liveのみ）
  G10 投稿2に「未確認」を含めない
  G11 通貨ペアの方向感（↑↓→）が原文の数値と一致するか（post2・report.md見出し・
     pairs_image。GBP/USDは原文の直接記述、無ければAUD/USD・AUD/GBPからの計算。
     liveのみ）
情報記録（不合格にはしない）:
  X加重文字数（全角=2換算）… Xプレミアム運用のため上限警告なし

exit codes: 0=PASS / 2=FAIL
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

FORBIDDEN_JA = ["ビットコイン", "イーサリアム", "暗号資産", "暗号通貨", "仮想通貨",
                "クリプト", "アルトコイン", "ステーブルコイン", "草コイン"]
FORBIDDEN_EN = ["BTC", "ETH", "Uniswap", "DeFi", "NFT", "Solana", "XRP", "Dogecoin",
                "USDT", "USDC", "Binance", "Coinbase",
                "Bitcoin", "Ethereum", "crypto", "cryptocurrency", "cryptocurrencies",
                "stablecoin", "stablecoins", "altcoin", "altcoins", "blockchain"]
FORBIDDEN_PAIRS = ["USD/CAD", "USDCAD", "USD/CHF", "USDCHF", "NZD/USD", "NZDUSD",
                   "EUR/JPY", "EURJPY", "AUD/JPY", "AUDJPY", "US30", "US500", "US100",
                   "NAS100", "SPX500"]
# 原文FXレート表のAUDクロス。対象5ペアの方向感を導出するための参照値として
# report_mdでのみ使用を許可する（G3では検出対象から除外。post2では引き続き検出）。
AUD_CROSS_EXEMPT = {"AUD/JPY", "AUDJPY", "AUD/GBP", "AUDGBP", "AUD/NZD", "AUDNZD",
                    "AUD/EUR", "AUDEUR", "AUD/CNH", "AUDCNH", "AUD/SGD", "AUDSGD",
                    "AUD/HKD", "AUDHKD", "AUD/CAD", "AUDCAD"}
TARGET_PAIRS = {"USD/JPY", "AUD/USD", "XAU/USD", "EUR/USD", "GBP/USD"}
PAIR_TAGS = ["#USDJPY", "#AUDUSD", "#XAUUSD", "#EURUSD", "#GBPUSD"]
PLACEHOLDERS = ["None", "null", "NaN", "undefined", "TBD", "XXX",
                "{DATE", "{PDF", "{WEEKDAY", "YYYY/MM/DD", "lorem"]


def tz_shift_hours(date: dt.date) -> int:
    """原文（Westpac、Australia/Sydney）からJST（Asia/Tokyo）への換算時差（時間）。
    generate_report.pyの同名関数と同じ計算（G9専用）。原文の"Times are AEST/AEDT."
    表記には依存せず、zoneinfoの実際のタイムゾーンデータから計算する。
    """
    syd = ZoneInfo("Australia/Sydney")
    tokyo = ZoneInfo("Asia/Tokyo")
    noon = dt.datetime(date.year, date.month, date.day, 12, 0)
    syd_offset = noon.replace(tzinfo=syd).utcoffset()
    tokyo_offset = noon.replace(tzinfo=tokyo).utcoffset()
    return int((syd_offset - tokyo_offset).total_seconds() // 3600)


def find_event_table_window(src_text: str, window_size: int = 2000):
    """原文から「Today's key data and events」のイベント表ブロックを抜き出す（G9専用）。
    見出しは"and events"まで含めて厳密に一致させる。これより短く"Today's key data"
    だけで探すと、原文の要約文中にある類似の文（例: "ahead of today's key data
    and central bank decisions"）を見出しと取り違え、本来のイベント表より前で
    窓を切り出してしまう（実例: 2026-10-28）。
    見つからない場合はNoneを返す。
    """
    head_m = re.search(r"Today.{0,2}s\s+key\s+data\s+and\s+events", src_text, re.IGNORECASE)
    if not head_m:
        return None
    window = src_text[head_m.start(): head_m.start() + window_size]
    end_m = re.search(r"Times are AE[SD]T\.", window)
    if end_m:
        window = window[:end_m.end()]
    return window


def times_in(text: str) -> set:
    """テキスト中の時刻表記（H:MM）をすべて抽出する（G9専用）。
    "-"（時刻なし）の行はこの正規表現にそもそもマッチしないため、比較対象から
    自然に除外される。境界判定は\\b（Unicode単語境界）ではなく前後に数字が
    無いことで行う。「翌0:00」のように時刻の直前が日本語の文字（Unicodeの
    単語構成文字）の場合、\\bではそこが境界と認識されず時刻を読み落とす
    （実例: 2026-10-22）。
    """
    out = set()
    for h, m in re.findall(r"(?<!\d)([0-2]?\d):([0-5]\d)(?!\d)", text):
        if int(h) <= 23:
            out.add(f"{int(h):02d}:{m}")
    return out


def shift_times(times: set, shift: int) -> set:
    """時刻集合の各値から時差shift時間を引く（24時間でラップ。G9専用）。"""
    out = set()
    for t in times:
        h, m = t.split(":")
        out.add(f"{(int(h) - shift) % 24:02d}:{m}")
    return out


def en_hit(token: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", text) is not None


def en_hit_i(token: str, text: str) -> bool:
    """G2専用。暗号通貨語は文頭・見出しで大文字になりうるため大小文字を無視して検出する"""
    return re.search(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])",
                     text, re.IGNORECASE) is not None


def expand_man_oku(text: str) -> str:
    """日本語の「万」「億」表記の数値を、桁が連続した数字に展開する（G8専用）。
    複合表記（例: "1万5800" → "15800"）と単純倍数（例: "5.8万" → "58000"、
    "3億" → "300000000"）の両方に対応。複合を先に展開してから単純倍数を処理する。
    """
    text = re.sub(r"(\d+)億(\d+)万(\d+)",
                  lambda m: str(int(m.group(1)) * 100_000_000 + int(m.group(2)) * 10_000 + int(m.group(3))), text)
    text = re.sub(r"(\d+)億(\d+)万(?!\d)",
                  lambda m: str(int(m.group(1)) * 100_000_000 + int(m.group(2)) * 10_000), text)
    text = re.sub(r"(\d+)億(\d+)(?!万|億)",
                  lambda m: str(int(m.group(1)) * 100_000_000 + int(m.group(2))), text)
    text = re.sub(r"(\d+)万(\d+)(?!万|億)",
                  lambda m: str(int(m.group(1)) * 10_000 + int(m.group(2))), text)

    def _scale(mul):
        def repl(m):
            v = float(m.group(1)) * mul
            return str(int(v)) if v == int(v) else str(v)
        return repl

    text = re.sub(r"(\d+(?:\.\d+)?)万", _scale(10_000), text)
    text = re.sub(r"(\d+(?:\.\d+)?)億", _scale(100_000_000), text)
    return text


def num_variants(plain: str) -> set:
    """整数の文字列表現から、PDF原文でありうる表記ゆれを生成する（G8専用）。
    例: "15800" → {"15800", "15.8k", "15.8"}（千単位のk表記・その数字部分）。
    例: "15500000000" → {"15500000000", "15.5b", "15.5bn"}（10億単位）。
    小数を含む値（FXレート等）はそのまま1件のみ返す。
    """
    variants = {plain}
    if plain.isdigit():
        n = int(plain)
        if n >= 1000 and n % 10 == 0:
            k = n / 1000
            k_str = f"{k:.2f}".rstrip("0").rstrip(".") or "0"
            variants.add(k_str + "k")
            # 小数を含む場合のみ末尾kなしも許容する（"50"のような裸の短い整数は
            # 無関係な数値と偶然一致しやすいため、区別しやすい小数表記に限定する）
            if "." in k_str:
                variants.add(k_str)
        # 100万単位（m/mn）・10億単位（b/bn）の表記ゆれ。k表記と異なり、裸の数値
        # （単位記号なしの小数のみの表記）は他の無関係な数値と偶然一致しやすいため
        # 一切対象に加えない（必ずm/mn/b/bnいずれかの単位記号付きのみ照合する）。
        for scale, suffixes in ((1_000_000, ("m", "mn")), (1_000_000_000, ("b", "bn"))):
            if n >= scale and n % 10 == 0:
                v = n / scale
                v_str = f"{v:.2f}".rstrip("0").rstrip(".") or "0"
                for suf in suffixes:
                    variants.add(v_str + suf)
    return variants


def weighted_len(s: str) -> int:
    """X の文字数換算の近似: CJK・全角=2、その他=1（URLは投稿禁止のため考慮不要）"""
    n = 0
    for ch in s:
        o = ord(ch)
        wide = (0x1100 <= o <= 0x11FF or 0x2E80 <= o <= 0xA4CF or 0xAC00 <= o <= 0xD7A3
                or 0xF900 <= o <= 0xFAFF or 0xFE30 <= o <= 0xFE4F or 0xFF00 <= o <= 0xFF60
                or 0xFFE0 <= o <= 0xFFE6 or o >= 0x20000)
        n += 2 if wide else 1
    return n


# G11: 通貨ペアの方向感（↑↓→）照合用のヘルパー
GBP_UP_WORDS = (r"(?:gain(?:ed|ing|s)?|ros[e]|rising|rise[sd]?|climb(?:ed|ing|s)?|"
                r"strengthen(?:ed|ing|s)?|advanc(?:ed|ing|es)?|ralli(?:ed|es|ying)?|"
                r"appreciat(?:ed|ing|es)?|add(?:ed|ing|s)?|up|higher)")
GBP_DOWN_WORDS = (r"(?:fell|falling|fall[s]?|dropp(?:ed|ing|s)?|declin(?:ed|ing|es)?|"
                  r"los(?:t|ing)|weaken(?:ed|ing|s)?|depreciat(?:ed|ing|es)?|"
                  r"slipp(?:ed|ing|s)?|slid(?:e|ing|es)?|eas(?:ed|ing|es)?|down|lower)")
GBP_FLAT_WORDS = r"(?:flat|unchanged|steady|little\s+changed)"
GBP_OTHER_CCY = r"(?:euro|yen|loonie|franc|dollar|greenback|USD|AUD|NZD)"
GBP_DIRECT_RE = re.compile(
    rf"\b(?:sterling|pound)\b"
    rf"(?P<gap1>(?:\s+\w+){{0,3}}?)"
    rf"\s+(?P<dir>{GBP_UP_WORDS}|{GBP_DOWN_WORDS}|{GBP_FLAT_WORDS})\b"
    # gap2と%をまとめて1つの省略可能な単位にする（%単独を省略可能にすると、
    # 0語でも%無しで即座に成立してしまい、2〜3語先に%がある場合でもgap2が
    # 広がらない。「%まで到達する」ことをこの単位全体の条件にすることで、
    # 近くに%がある場合は正しく広がる）
    rf"(?:(?P<gap2>(?:\s+\w+){{0,3}}?)\s*\(?(?P<pct>[+-]?\d+(?:\.\d+)?)\s*%\)?)?",
    re.IGNORECASE)
# %。AUD/USD・AUD/GBPとも原文は小数点1桁までの丸めのため、差が小さい日は丸め誤差で
# 符号が反転しうる（実例: 2026-09-23・2026-11-02）。この範囲はGBP/USDを判定しない。
GBP_CROSS_THRESHOLD = 0.15
PAIR_TAG = {"USD/JPY": "#USDJPY", "AUD/USD": "#AUDUSD", "XAU/USD": "#XAUUSD",
            "EUR/USD": "#EURUSD", "GBP/USD": "#GBPUSD"}
ARROW_TO_DIR = {"↑": "up", "↓": "down", "→": "flat"}


def table_change_pct(src_text: str, label: str):
    """原文の表（FXレート表・Commoditiesなど）で「LABEL 値 変化%」の形に
    並んでいる行から変化率（%、符号付き）を取り出す（G11専用）。本文中に
    LABELが単独で出てくる箇所は値と%がこの並びで連続しないため一致しない。
    """
    m = re.search(rf"\b{re.escape(label)}\s+[\d,.]+\s+([+-]?\d+(?:\.\d+)?)%", src_text)
    return float(m.group(1)) if m else None


def sign_dir(v: float) -> str:
    if v > 0:
        return "up"
    if v < 0:
        return "down"
    return "flat"


def gbp_direct_statement(src_text: str):
    """原文にポンド（sterling/pound）自身の上昇・下落・横ばいの直接記述があれば
    (向き, 一致箇所の文字列) を返す（G11専用）。見つからなければ (None, None)。
    westpac.txtは2段組のPDF抽出で行が混ざり、1つの文として完結しないことが多い
    （例: 他通貨と動詞・%を共有する "the euro and\\nsterling both gained 0.1%." や、
    "pound losing 0.4% and 0.2% respectively" のように%が複数並ぶ）。誤って他通貨の
    数値をポンドの値として取り違えないよう、方向語の前後だけでなく一致箇所の前後
    各40字も含めて他通貨名や"and"・"respectively" が無く、方向語の直後に%が
    明確に1つだけ続く場合に限って採用する（"pound losing 0.4% and 0.2%
    respectively"は、%の直後に続く"and 0.2%"・"respectively"が一致箇所の外に
    出るため、一致箇所内だけを見る判定では取り違えを防げない）。それ以外
    （あいまい・%が見つからない）は見送り、呼び出し側でAUD/USD・AUD/GBPからの
    計算に委ねる。
    """
    for m in GBP_DIRECT_RE.finditer(src_text):
        gap1 = m.group("gap1")
        # gap2・pctは%まで到達した場合のみ値を持つ単位の内側にあるため、
        # %が近くに無い日は両方ともNone（空文字ではない）になる
        gap2 = m.group("gap2") or ""
        word = m.group("dir")
        if re.fullmatch(GBP_UP_WORDS, word, re.IGNORECASE):
            direction = "up"
        elif re.fullmatch(GBP_DOWN_WORDS, word, re.IGNORECASE):
            direction = "down"
        else:
            direction = "flat"
        start, end = m.span()
        context_before = src_text[max(0, start - 40):start]
        context_after = src_text[end:end + 40]
        if (re.search(GBP_OTHER_CCY, gap1, re.IGNORECASE) or re.search(GBP_OTHER_CCY, gap2, re.IGNORECASE)
                or re.search(rf"{GBP_OTHER_CCY}\s+and\s*$", context_before, re.IGNORECASE)):
            continue
        if ("and" in gap1.lower() or "respectively" in (gap1 + gap2).lower()
                or "respectively" in context_after.lower()
                or re.match(r"\s*and\s+[+-]?\d", context_after, re.IGNORECASE)):
            continue
        if direction != "flat" and m.group("pct") is None:
            continue
        return direction, m.group(0).strip().replace("\n", " ")
    return None, None


def expected_pair_directions(src_text: str) -> dict:
    """原文から対象5ペアの期待される向き（up/down/flat）を求める（G11専用）。
    戻り値は {ペア名: (向き, 根拠の説明)}。原文から判断材料が全く得られない
    （または根拠が弱すぎる）ペアはキーに含めず、その日はそのペアを判定しない。
    GBP/USDは厳守事項13と同じ優先順位：(a) 原文のポンド自身の直接記述があれば
    それを最優先（(1+AUD/USD)/(1+AUD/GBP)-1の計算と向きが食い違う日があっても、
    直接記述を正とする）。(b) 直接記述が無い場合のみ、AUD/USD・AUD/GBPの前日比
    からこの式で計算し、絶対値がGBP_CROSS_THRESHOLD未満の日は判定しない。
    """
    out = {}
    for pair in ("USD/JPY", "AUD/USD", "EUR/USD"):
        v = table_change_pct(src_text, pair)
        if v is not None:
            out[pair] = (sign_dir(v), f"原文FXレート表 {pair} {v:+.1f}%")
    gold = table_change_pct(src_text, "Gold")
    if gold is not None:
        out["XAU/USD"] = (sign_dir(gold), f"原文Commodities表 Gold {gold:+.1f}%")

    direct_dir, direct_quote = gbp_direct_statement(src_text)
    if direct_dir is not None:
        out["GBP/USD"] = (direct_dir, f"原文の直接記述:「{direct_quote}」")
    else:
        aud_usd = table_change_pct(src_text, "AUD/USD")
        aud_gbp = table_change_pct(src_text, "AUD/GBP")
        if aud_usd is not None and aud_gbp is not None:
            computed = aud_usd - aud_gbp
            if abs(computed) >= GBP_CROSS_THRESHOLD:
                out["GBP/USD"] = (sign_dir(computed),
                                  f"計算: AUD/USD{aud_usd:+.1f}% − AUD/GBP{aud_gbp:+.1f}% = {computed:+.2f}%")
    return out


def post2_pair_dir(p2: str, pair: str):
    """post2.txt中の該当ペアのタグ行から矢印の向きを読む（G11専用）。
    現値の記載がある行（例: "#USDJPY 158.32 →"・単位が値に直接続く
    "#USDJPY 159.85円 →"・"#XAUUSD 4,026.47ドル →"）・無い行（例:
    "#GBPUSD ↑"）のいずれにも対応する。
    """
    m = re.search(rf"{re.escape(PAIR_TAG[pair])}\s+(?:[\d.,]+(?:円|ドル)?\s+)?([↑↓→])", p2)
    return ARROW_TO_DIR.get(m.group(1)) if m else None


def report_md_pair_dir(md: str, pair: str):
    """report.md「## 2」の該当ペアの見出し（例: "### GBP/USD ― 上昇（↑）"）から
    矢印の向きを読む（G11専用）。
    """
    m = re.search(rf"###\s*{re.escape(pair)}\s*―.*?[（(]([↑↓→])[）)]", md)
    return ARROW_TO_DIR.get(m.group(1)) if m else None


def pairs_image_pair_dir(data: dict, pair: str):
    """report_data.jsonのpairs_imageから該当ペアのdirを読む（G11専用）。
    その日の画像3ペアに含まれない場合はNone（その場所は判定対象外）。
    """
    for p in data.get("pairs_image", []):
        if p.get("pair") == pair:
            return p.get("dir")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = (dt.date.fromisoformat(args.date) if args.date
            else dt.datetime.now(ZoneInfo("Asia/Tokyo")).date())
    ddir = os.path.join("outputs", date.isoformat())

    data = json.load(open(os.path.join(ddir, "report_data.json"), encoding="utf-8"))
    md = open(os.path.join(ddir, "report.md"), encoding="utf-8").read()
    p1 = open(os.path.join(ddir, "post1.txt"), encoding="utf-8").read()
    p2 = open(os.path.join(ddir, "post2.txt"), encoding="utf-8").read()
    sample = os.path.exists(os.path.join(ddir, "sample_mode.flag"))
    all_text = "\n".join([md, p1, p2, json.dumps(data, ensure_ascii=False)])

    gates, warnings = [], []

    def gate(gid, name, ok, detail=""):
        gates.append({"id": gid, "name": name,
                      "status": "PASS" if ok else "FAIL", "detail": detail})
        return ok

    # G1 日付整合
    slash = date.strftime("%Y/%m/%d")
    ja = f"{date.year}年{date.month}月{date.day}日"
    ok1 = data.get("date_jst") == date.isoformat() and ja in md and slash in p2 and slash in md
    gate("G1", "日付整合", ok1,
         f"date_jst={data.get('date_jst')} / 本文に「{ja}」/ 投稿2と本文に「{slash}」を要求")

    # G2 暗号通貨語ゼロ
    hits = [w for w in FORBIDDEN_JA if w in all_text] + \
           [w for w in FORBIDDEN_EN if en_hit_i(w, all_text)]
    gate("G2", "暗号通貨語の混入ゼロ", not hits, "検出: " + ", ".join(hits) if hits else "")

    # G3 対象5ペア限定
    # report_mdはAUDクロス（方向感導出の参照値）を許可、post2は全FORBIDDEN_PAIRSを検出する
    bad_md = [w for w in FORBIDDEN_PAIRS if w not in AUD_CROSS_EXEMPT and en_hit(w, md)]
    bad_p2 = [w for w in FORBIDDEN_PAIRS if en_hit(w, p2)]
    bad = sorted(set(bad_md) | set(bad_p2))
    tags_missing = [t for t in PAIR_TAGS if t not in p2]
    img_pairs = {p.get("pair", "") for p in data.get("pairs_image", [])}
    img_bad = sorted(img_pairs - TARGET_PAIRS)
    ok3 = not bad and not tags_missing and not img_bad
    gate("G3", "対象5ペア限定", ok3,
         "; ".join(x for x in [
             f"対象外ペア検出: {', '.join(bad)}" if bad else "",
             f"投稿2に不足タグ: {', '.join(tags_missing)}" if tags_missing else "",
             f"画像データに対象外: {', '.join(img_bad)}" if img_bad else ""] if x))

    # G4 プレースホルダ残存なし
    ph = [w for w in PLACEHOLDERS
          if (w in (md + p1 + p2) if not w.isascii() or not w.isalpha()
              else en_hit(w, md + p1 + p2))]
    ph += re.findall(r"\{[A-Z_]{3,}\}", md + p1 + p2)
    gate("G4", "プレースホルダ残存なし", not ph, "検出: " + ", ".join(set(ph)) if ph else "")

    # G5 出典表記
    ok5 = ("Westpac IQ Morning Report" in md) and (f"Westpac IQ Morning Report {slash}" in p2)
    gate("G5", "出典表記（本文・投稿2）", ok5)

    # G6 規定ハッシュタグ
    # ハッシュタグ本数のA/B検証中（A案=2個）。post1の2個目は日替わりの材料タグのため固定チェックしない
    p1_missing = [t for t in ["#ドル円"] if t not in p1]
    p2_missing = [t for t in ["#ドル円", "#為替"] if t not in p2]
    gate("G6", "規定ハッシュタグ", not p1_missing and not p2_missing,
         f"投稿1不足: {p1_missing} / 投稿2不足: {p2_missing}" if p1_missing or p2_missing else "")

    # G7 投稿にURLなし
    urls = re.findall(r"https?://\S+", p1 + "\n" + p2)
    gate("G7", "投稿にURLなし（Intent URL禁止）", not urls,
         "検出: " + ", ".join(urls[:3]) if urls else "")

    # G8 数値のPDF原文照合（liveのみ）
    if sample:
        gates.append({"id": "G8", "name": "数値のPDF原文照合", "status": "SKIP",
                      "detail": "サンプルモードのため対象外"})
    else:
        src = os.path.join("sources", date.isoformat(), "westpac.txt")
        if not os.path.exists(src):
            gate("G8", "数値のPDF原文照合", False, "PDF抽出テキストが見つからない")
        else:
            pdf_norm = open(src, encoding="utf-8").read().replace(",", "")
            body = re.sub(r"\b\d{1,2}:\d{2}\b", " ", p2)          # 時刻を除外
            body = re.sub(rf"\b{date.month}/{date.day}\b", " ", body)  # 日付表記を除外
            body = body.replace(slash, " ")
            body = expand_man_oku(body)                          # 「1万5800」等を「15800」へ展開
            nums = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", body)  # 桁を途中で分断しない
            checked, missing = [], []
            for n in dict.fromkeys(nums):
                plain = n.replace(",", "")
                if "." not in plain and len(plain) < 2:
                    continue  # 箇条書き番号等は対象外
                checked.append(plain)
                if not any(v in pdf_norm for v in num_variants(plain)):
                    missing.append(plain)
            gate("G8", "数値のPDF原文照合", not missing,
                 (f"未照合: {', '.join(missing)}（原文に存在しない数値）" if missing
                  else f"{len(checked)}個の数値を照合しすべて原文に存在"))

    # G9 イベント時刻のJST換算チェック（原文時刻を正しい時差で換算した結果と
    # 本文イベント表が一致するか・liveのみ）
    if sample:
        gates.append({"id": "G9", "name": "イベント時刻JST換算チェック", "status": "SKIP",
                      "detail": "サンプルモードのため対象外"})
    else:
        src_path = os.path.join("sources", date.isoformat(), "westpac.txt")
        if not os.path.exists(src_path):
            gate("G9", "イベント時刻JST換算チェック", False, "PDF抽出テキストが見つからない")
        else:
            src_text = open(src_path, encoding="utf-8").read()
            window = find_event_table_window(src_text)
            if window is None:
                gate("G9", "イベント時刻JST換算チェック", True,
                     "原文に「Today's key data」ブロックが見つからず対象外（構成変更の可能性。手動確認推奨）")
            else:
                shift = tz_shift_hours(date)
                src_times = times_in(window)
                expected_times = shift_times(src_times, shift)
                ev_m = re.search(r"##\s*3\.\s*本日の重要イベント(.*?)(?:\n##|\n出典|\Z)", md, re.DOTALL)
                md_times = times_in(ev_m.group(1)) if ev_m else set()
                ok9 = (not src_times) or expected_times == md_times
                gate("G9", "イベント時刻JST換算チェック", ok9,
                     (f"時差{shift}時間で換算した期待値{sorted(expected_times)}と"
                      f"本文イベント表{sorted(md_times)}が一致"
                      if ok9 else
                      f"時差{shift}時間で換算した期待値{sorted(expected_times)}と"
                      f"本文イベント表{sorted(md_times)}が不一致"
                      f"（原文時刻{sorted(src_times)}。原文のAEST/AEDT表記は無視し"
                      f"zoneinfoベースの時差{shift}時間を正としている）"))

    # G10 投稿2に「未確認」を含めない
    ok10 = "未確認" not in p2
    gate("G10", "投稿2に「未確認」を含めない", ok10,
         "「未確認」を検出（現値が原文にないペアは現値部分を省略する形式にする）" if not ok10 else "")

    # G11 通貨ペアの方向感（↑↓→）照合（原文の数値と一致するか・liveのみ）
    if sample:
        gates.append({"id": "G11", "name": "通貨ペア方向感の照合", "status": "SKIP",
                      "detail": "サンプルモードのため対象外"})
    else:
        src_path11 = os.path.join("sources", date.isoformat(), "westpac.txt")
        if not os.path.exists(src_path11):
            gate("G11", "通貨ペア方向感の照合", False, "PDF抽出テキストが見つからない")
        else:
            src_text11 = open(src_path11, encoding="utf-8").read()
            expected11 = expected_pair_directions(src_text11)
            mismatches11 = []
            for pair, (edir, basis) in expected11.items():
                for loc, actual in (
                    ("post2", post2_pair_dir(p2, pair)),
                    ("report.mdの見出し", report_md_pair_dir(md, pair)),
                    ("pairs_image", pairs_image_pair_dir(data, pair)),
                ):
                    if actual is not None and actual != edir:
                        mismatches11.append(
                            f"{pair}（{loc}）: 期待={edir} 実際={actual}（根拠: {basis}）")
            gate("G11", "通貨ペア方向感の照合", not mismatches11,
                 "; ".join(mismatches11) if mismatches11 else
                 f"{len(expected11)}ペアの向きが原文と一致（判定対象外: "
                 f"{', '.join(sorted(TARGET_PAIRS - expected11.keys())) or 'なし'}）")

    # 情報: X加重文字数（Xプレミアム運用のため280字は制約にならず、上限警告は表示しない）
    for name, txt in (("post1", p1), ("post2", p2)):
        wl = weighted_len(txt)
        gates.append({"id": "I1" if name == "post1" else "I2",
                      "name": f"{name} 加重文字数", "status": "INFO",
                      "detail": f"{wl}"})

    # 情報: post1の「→」行の読点過多（読点2つ以上＝1行に複数事実を詰め込んでいる疑い。FAILにはしない）
    heavy_lines = []
    for i, ln in enumerate(p1.split("\n"), start=1):
        if ln.startswith("→"):
            n = ln[1:].count("、")
            if n >= 2:
                heavy_lines.append(f"{i}行目 読点{n}個")
    gates.append({"id": "I3", "name": "post1 →行の読点過多", "status": "INFO",
                  "detail": ", ".join(heavy_lines) if heavy_lines else "なし"})

    overall = "PASS" if all(g["status"] != "FAIL" for g in gates) else "FAIL"
    audit = {
        "run_date": date.isoformat(),
        "mode": "SAMPLE" if sample else "LIVE",
        "overall": overall,
        "gates": gates,
        "warnings": warnings,
        "verified_at_jst": dt.datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds"),
    }
    with open(os.path.join(ddir, "audit.json"), "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print(f"[verify_report] overall={overall}")
    for g in gates:
        print(f"  {g['id']} {g['name']}: {g['status']} {g['detail']}")
    return 0 if overall == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
