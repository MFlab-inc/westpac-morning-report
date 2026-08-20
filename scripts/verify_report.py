#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_report.py — 納品前の機械検証ゲート。結果は outputs/<date>/audit.json に保存。

ゲート:
  G1 日付整合 / G2 暗号通貨語の混入ゼロ / G3 対象5ペア限定 / G4 プレースホルダ残存なし
  G5 出典表記 / G6 規定ハッシュタグ / G7 投稿にURLなし / G8 数値のPDF原文照合（liveのみ）
  G9 イベント時刻JST換算チェック（原文AEST/AEDT時刻と本文時刻が完全一致＝未換算の疑い。liveのみ）
  G10 投稿2に「未確認」を含めない
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
TARGET_PAIRS = {"USD/JPY", "AUD/USD", "XAU/USD", "EUR/USD", "GBP/USD"}
PAIR_TAGS = ["#USDJPY", "#AUDUSD", "#XAUUSD", "#EURUSD", "#GBPUSD"]
PLACEHOLDERS = ["None", "null", "NaN", "undefined", "TBD", "XXX",
                "{DATE", "{PDF", "{WEEKDAY", "YYYY/MM/DD", "lorem"]


def en_hit(token: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", text) is not None


def en_hit_i(token: str, text: str) -> bool:
    """G2専用。暗号通貨語は文頭・見出しで大文字になりうるため大小文字を無視して検出する"""
    return re.search(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])",
                     text, re.IGNORECASE) is not None


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
    bad = [w for w in FORBIDDEN_PAIRS if en_hit(w, md + "\n" + p2)]
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
            nums = re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?", body)
            checked, missing = [], []
            for n in dict.fromkeys(nums):
                plain = n.replace(",", "")
                if "." not in plain and len(plain) < 2:
                    continue  # 箇条書き番号等は対象外
                checked.append(plain)
                if plain not in pdf_norm:
                    missing.append(plain)
            gate("G8", "数値のPDF原文照合", not missing,
                 (f"未照合: {', '.join(missing)}（原文に存在しない数値）" if missing
                  else f"{len(checked)}個の数値を照合しすべて原文に存在"))

    # G9 イベント時刻のJST換算チェック（AEST/AEDT未換算の疑い・liveのみ）
    if sample:
        gates.append({"id": "G9", "name": "イベント時刻JST換算チェック", "status": "SKIP",
                      "detail": "サンプルモードのため対象外"})
    else:
        src_path = os.path.join("sources", date.isoformat(), "westpac.txt")
        if not os.path.exists(src_path):
            gate("G9", "イベント時刻JST換算チェック", False, "PDF抽出テキストが見つからない")
        else:
            src_text = open(src_path, encoding="utf-8").read()
            head_m = re.search(r"Today.{0,2}s\s+key\s+data", src_text, re.IGNORECASE)
            if not head_m:
                gate("G9", "イベント時刻JST換算チェック", True,
                     "原文に「Today's key data」ブロックが見つからず対象外（構成変更の可能性。手動確認推奨）")
            else:
                window = src_text[head_m.start(): head_m.start() + 2000]
                end_m = re.search(r"Times are AE[SD]T\.", window)
                if end_m:
                    window = window[:end_m.end()]

                def times_in(text):
                    out = set()
                    for h, m in re.findall(r"\b([0-2]?\d):([0-5]\d)\b", text):
                        if int(h) <= 23:
                            out.add(f"{int(h):02d}:{m}")
                    return out

                src_times = times_in(window)
                ev_m = re.search(r"##\s*3\.\s*本日の重要イベント(.*?)(?:\n##|\n出典|\Z)", md, re.DOTALL)
                md_times = times_in(ev_m.group(1)) if ev_m else set()
                suspicious = bool(src_times) and src_times == md_times
                gate("G9", "イベント時刻JST換算チェック", not suspicious,
                     (f"原文AEST/AEDT時刻{sorted(src_times)}と本文イベント表{sorted(md_times)}が完全一致"
                      "＝JST換算されていない疑い" if suspicious
                      else f"原文候補{sorted(src_times)} / 本文{sorted(md_times)}（不一致のため換算済みと判定）"))

    # G10 投稿2に「未確認」を含めない
    ok10 = "未確認" not in p2
    gate("G10", "投稿2に「未確認」を含めない", ok10,
         "「未確認」を検出（現値が原文にないペアは現値部分を省略する形式にする）" if not ok10 else "")

    # 情報: X加重文字数（Xプレミアム運用のため280字は制約にならず、上限警告は表示しない）
    for name, txt in (("post1", p1), ("post2", p2)):
        wl = weighted_len(txt)
        gates.append({"id": "I1" if name == "post1" else "I2",
                      "name": f"{name} 加重文字数", "status": "INFO",
                      "detail": f"{wl}"})

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
