#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capture_charts.py — https://6forex.netlify.app/ の1H足チャート一覧を1920x1080で撮影する。

- 表示期間はサイトのデフォルト（約1ヶ月）のまま。切り替え操作はしない。
- TradingViewウィジェットの描画完了を待つため長めに待機する。
- 自作チャートでの代替はしない（スキル厳守事項）。
"""
import argparse
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

DEFAULT_URL = "https://6forex.netlify.app/"


def log(msg):
    print(f"[capture_charts] {msg}", flush=True)


def shoot(page, out_path):
    page.screenshot(path=out_path, type="jpeg", quality=90)
    return os.path.getsize(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--out", default=None)
    ap.add_argument("--wait", type=int, default=22, help="初期待機秒数")
    args = ap.parse_args()

    today = (dt.date.fromisoformat(args.date) if args.date
             else dt.datetime.now(ZoneInfo("Asia/Tokyo")).date())
    out = args.out or os.path.join("outputs", today.isoformat(), "charts_1h.jpg")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_context(
            viewport={"width": 1920, "height": 1080}, device_scale_factor=1,
        ).new_page()
        log(f"open: {args.url}")
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(args.wait * 1000)
        size = shoot(page, out)
        log(f"shot 1: {size} bytes")
        if size < 120_000:  # 描画未完（ほぼ無地）の疑い → 追加待機して撮り直し
            page.wait_for_timeout(12_000)
            size = shoot(page, out)
            log(f"shot 2: {size} bytes")
        browser.close()

    meta = {"url": args.url, "bytes": size,
            "captured_at_jst": dt.datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")}
    with open(os.path.join(os.path.dirname(out), "charts_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    if size < 120_000:
        log("WARNING: 画像サイズが小さく描画未完の可能性。Issueで目視確認してください")
    log(f"saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
