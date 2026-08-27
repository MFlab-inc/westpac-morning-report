#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_report.py — 抽出済みPDFテキストからレポート一式のデータ（JSON）を生成する。

- Claude API（環境変数 ANTHROPIC_API_KEY）を使用。モデルは WMR_MODEL で上書き可。
- --sample 指定時はAPIを呼ばず sample_data/report_data_sample.json を当日日付に
  書き換えて使用（初回動作テスト・環境検証用）。

exit codes: 0=成功 / 6=生成失敗（JSON不正が2回連続 等）
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-6"
REQUIRED_KEYS = ["date_jst", "themes", "pairs_image", "report_md", "post1", "post2"]

TAG_RULE_A = ("post1の最終行は「#ドル円」＋その日の最重要材料タグ1個の計2個とする。"
              "該当する材料がない日は「#ドル円 #為替」の2個とする。")
TAG_RULE_B = ("post1の最終行は「#FX #ドル円」＋その日の最重要材料タグ1個の計3個とする。"
              "該当する材料がない日は「#FX #ドル円 #為替」の3個とする。")


def tag_variant_for(date: dt.date) -> str:
    """ハッシュタグA/BテストのA/B判定。ISO週番号が偶数ならB、奇数ならA。"""
    return "B" if date.isocalendar()[1] % 2 == 0 else "A"


def log(msg):
    print(f"[generate_report] {msg}", flush=True)


def jdate(d: dt.date):
    wd = "月火水木金土日"[d.weekday()]
    return {
        "DATE_ISO": d.isoformat(),
        "DATE_SLASH": d.strftime("%Y/%m/%d"),
        "DATE_MD": f"{d.month}/{d.day}",
        "DATE_JA": f"{d.year}年{d.month}月{d.day}日",
        "WEEKDAY_JA": wd,
    }


def strip_fence(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        s = s[i:j + 1]
    return s


def call_claude(prompt: str, model: str) -> str:
    import requests
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY が未設定です（リポジトリSecretsに登録してください）")
    body = {
        "model": model,
        "max_tokens": 8000,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    r = requests.post(API_URL, timeout=300, json=body, headers={
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    if r.status_code != 200:
        raise RuntimeError(f"Claude API error {r.status_code}: {r.text[:500]}")
    data = r.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def load_sample(date: dt.date) -> dict:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "sample_data", "report_data_sample.json")
    raw = open(path, encoding="utf-8").read()
    src = json.loads(raw)
    src_d = dt.date.fromisoformat(src["date_jst"])
    sv, dv = jdate(src_d), jdate(date)
    for k in ("DATE_JA", "DATE_SLASH", "DATE_MD", "DATE_ISO"):
        raw = raw.replace(sv[k], dv[k])
    raw = raw.replace(f"（{sv['WEEKDAY_JA']}）", f"（{dv['WEEKDAY_JA']}）")
    raw = raw.replace(f"({sv['WEEKDAY_JA']})", f"({dv['WEEKDAY_JA']})")
    data = json.loads(raw)
    data["date_jst"] = date.isoformat()
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--sample", action="store_true", help="APIを呼ばずサンプルで生成")
    args = ap.parse_args()

    date = (dt.date.fromisoformat(args.date) if args.date
            else dt.datetime.now(ZoneInfo("Asia/Tokyo")).date())
    out_dir = os.path.join("outputs", date.isoformat())
    os.makedirs(out_dir, exist_ok=True)

    tag_variant = tag_variant_for(date)
    log(f"tag_variant: {tag_variant} (ISO week {date.isocalendar()[1]})")

    if args.sample:
        log("サンプルモード（API呼び出しなし）")
        data = load_sample(date)
        data["tag_variant"] = tag_variant
        with open(os.path.join(out_dir, "sample_mode.flag"), "w") as f:
            f.write("1")
    else:
        src_txt = os.path.join("sources", date.isoformat(), "westpac.txt")
        if not os.path.exists(src_txt):
            log(f"PDF抽出テキストがありません: {src_txt}（先に fetch_westpac.py を実行）")
            return 6
        pdf_text = open(src_txt, encoding="utf-8").read()[:28000]
        meta_path = os.path.join("sources", date.isoformat(), "meta.json")
        pdf_url = ""
        if os.path.exists(meta_path):
            pdf_url = json.load(open(meta_path, encoding="utf-8")).get("pdf_url", "")

        here = os.path.dirname(os.path.abspath(__file__))
        template = open(os.path.join(here, "..", "prompts", "generate_prompt.md"),
                        encoding="utf-8").read()
        prompt = template
        for k, v in jdate(date).items():
            prompt = prompt.replace("{" + k + "}", v)
        prompt = prompt.replace("{PDF_TEXT}", pdf_text)
        prompt = prompt.replace("{TAG_RULE}", TAG_RULE_B if tag_variant == "B" else TAG_RULE_A)

        model = os.environ.get("WMR_MODEL", DEFAULT_MODEL)
        log(f"model: {model} / prompt: {len(prompt)} chars")
        data = None
        for attempt in (1, 2):
            raw = call_claude(prompt if attempt == 1 else
                              prompt + "\n\n【再指示】前回の出力はJSONとして解釈できませんでした。"
                                       "説明文・コードフェンスなしで、有効なJSONオブジェクトのみを出力してください。",
                              model)
            try:
                data = json.loads(strip_fence(raw))
                break
            except Exception as e:
                log(f"JSON解析失敗（{attempt}回目）: {e}")
                with open(os.path.join(out_dir, f"raw_attempt{attempt}.txt"), "w",
                          encoding="utf-8") as f:
                    f.write(raw)
        if data is None:
            return 6
        missing = [k for k in REQUIRED_KEYS if k not in data]
        if missing:
            log(f"必須キー欠落: {missing}")
            return 6
        data["date_jst"] = date.isoformat()  # 日付は実行側で確定させる
        data["pdf_url"] = pdf_url
        data.setdefault("source_label", "Westpac IQ Morning Report")
        data["tag_variant"] = tag_variant

    with open(os.path.join(out_dir, "report_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(data["report_md"])
    with open(os.path.join(out_dir, "post1.txt"), "w", encoding="utf-8") as f:
        f.write(data["post1"])
    with open(os.path.join(out_dir, "post2.txt"), "w", encoding="utf-8") as f:
        f.write(data["post2"])
    log(f"saved: {out_dir}/report_data.json, report.md, post1.txt, post2.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
