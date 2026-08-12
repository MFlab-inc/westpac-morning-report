#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_westpac.py — Westpac IQ Morning Report の当日PDFを取得しテキスト抽出する。

ルール（Manus運用を踏襲）:
- 必ず https://www.westpaciq.com.au/topic.morningreport から当日リンクを探す。
- PDFのURLパスは月替わりで変わるため、URLの直打ち推測は絶対にしない。
- 当日分が未発行なら exit code 3 で終了（呼び出し側が最終試行時のみ通知）。

exit codes:
  0=成功 / 3=当日分未発行の可能性 / 4=サイト構造の変化等で候補が見つからない / 5=PDFテキスト抽出不良
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

TOPIC_URL = "https://www.westpaciq.com.au/topic.morningreport"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def date_tokens(d: dt.date):
    m = MONTHS[d.month - 1]
    return [
        f"{m} {d.day} {d.year}",          # August 12 2026（記事カードの表記）
        f"{m} {d.day}, {d.year}",
        f"{d.day} {m} {d.year}",          # 12 August 2026（PDF/本文の表記）
        f"{m[:3]} {d.day} {d.year}",
        d.strftime("%Y-%m-%d"),
        d.strftime("%Y%m%d"),
    ]


def log(msg):
    print(f"[fetch_westpac] {msg}", flush=True)


def save_debug(dirpath, name, content):
    os.makedirs(dirpath, exist_ok=True)
    p = os.path.join(dirpath, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    log(f"debug saved: {p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="対象日 YYYY-MM-DD（省略時=JST今日）")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    today = (dt.date.fromisoformat(args.date) if args.date
             else dt.datetime.now(ZoneInfo("Asia/Tokyo")).date())
    tokens = date_tokens(today)
    prev_tokens = date_tokens(today - dt.timedelta(days=1)) + date_tokens(today - dt.timedelta(days=3))

    out_dir = args.out_dir or os.path.join("sources", today.isoformat())
    os.makedirs(out_dir, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 960},
                                  locale="en-AU", timezone_id="Australia/Sydney")
        page = ctx.new_page()
        log(f"open topic page: {TOPIC_URL}")
        page.goto(TOPIC_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(9000)  # 一覧はJS描画のため待機

        anchors = page.eval_on_selector_all(
            "a", "els => els.map(e => ({href: e.href || '', text: (e.innerText || '').trim()}))")
        log(f"anchors on topic page: {len(anchors)}")

        # 記事候補: hrefかリンクテキストに morning report を含む記事URL
        seen, cands = set(), []
        for a in anchors:
            href, text = a["href"], a["text"]
            if not href or "topic.morningreport" in href:
                continue
            lower_h, lower_t = href.lower(), text.lower()
            is_article = re.search(r"westpaciq\.com\.au/.+/\d{4}/\d{2}/", href)
            if (is_article or href.lower().endswith(".pdf")) and \
               ("morning" in lower_h or "morning report" in lower_t):
                if href not in seen:
                    seen.add(href)
                    cands.append(a)
        log(f"morning report candidates: {len(cands)}")
        for c in cands[:6]:
            log(f"  cand: {c['href']}  [{c['text'][:40]}]")

        if not cands:
            save_debug(out_dir, "debug_topic.html", page.content())
            log("候補ゼロ。サイト構造が変わった可能性（debug_topic.htmlを確認）")
            browser.close()
            return 4

        pdf_url, article_url = None, None

        # 1) 一覧に当日トークン入りの直接PDFリンクがある場合
        for c in cands:
            if c["href"].lower().endswith(".pdf") and any(t in c["href"] for t in tokens):
                pdf_url = c["href"]
                break

        # 2) 記事ページを新しい順に開き、当日日付を確認してPDFリンクを探す
        old_seen = False
        if not pdf_url:
            for c in [x for x in cands if not x["href"].lower().endswith(".pdf")][:4]:
                log(f"open article: {c['href']}")
                try:
                    page.goto(c["href"], wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(7000)
                except Exception as e:
                    log(f"  記事を開けず: {e}")
                    continue
                body = ""
                try:
                    body = page.inner_text("body")
                except Exception:
                    pass
                content = page.content()
                if any(t in body for t in tokens) or any(t in content for t in tokens):
                    article_url = page.url
                    pdfs = page.eval_on_selector_all(
                        "a", "els => els.map(e => e.href || '').filter(h => h.toLowerCase().includes('.pdf'))")
                    pdfs += re.findall(r"https?://[^\s\"'<>]+?\.pdf", content, flags=re.I)
                    pdfs = [p for p in dict.fromkeys(pdfs) if p]
                    if pdfs:
                        prefer = [p for p in pdfs if "morning" in p.lower()] or pdfs
                        pdf_url = prefer[0]
                        break
                    save_debug(out_dir, "debug_article.html", content)
                    log("  当日記事だがPDFリンク不検出（debug_article.htmlを確認）")
                elif any(t in body for t in prev_tokens):
                    old_seen = True
                    log("  過去日付の記事。次の候補へ")
                else:
                    log("  日付を確認できず。次の候補へ")

        if not pdf_url:
            save_debug(out_dir, "debug_topic.html", page.content())
            browser.close()
            if old_seen:
                log("最新候補が過去日付＝当日分は未発行の可能性")
                return 3
            log("当日PDFを特定できず（未発行または構造変化）")
            return 3

        log(f"PDF: {pdf_url}")
        resp = page.request.get(pdf_url, timeout=60000)
        data = resp.body()
        browser.close()

    if not data.startswith(b"%PDF"):
        with open(os.path.join(out_dir, "debug_pdf_response.bin"), "wb") as f:
            f.write(data[:200000])
        log("PDFではない応答を受信（認証壁の可能性）。debug_pdf_response.bin を確認")
        return 4

    pdf_path = os.path.join(out_dir, "westpac.pdf")
    with open(pdf_path, "wb") as f:
        f.write(data)
    log(f"saved: {pdf_path} ({len(data)} bytes)")

    import pdfplumber
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        for pg in pdf.pages:
            text_parts.append(pg.extract_text() or "")
    text = "\n\n".join(text_parts)
    txt_path = os.path.join(out_dir, "westpac.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    meta = {
        "date": today.isoformat(),
        "article_url": article_url,
        "pdf_url": pdf_url,
        "pages": n_pages,
        "chars": len(text),
        "fetched_at_jst": dt.datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds"),
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log(f"text extracted: {len(text)} chars / {n_pages} pages")

    if len(text) < 800:
        log("抽出テキストが少なすぎます（スキャンPDF等の可能性）")
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
