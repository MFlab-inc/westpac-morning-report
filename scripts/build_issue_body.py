#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_issue_body.py — 検収用Issueのタイトルと本文を生成する。

出力: outputs/<date>/issue_title.txt / issue_body.md
画像は同リポジトリにコミットされた outputs/<date>/*.png|jpg を
https://github.com/<repo>/raw/<branch>/... 形式で埋め込む（プライベート
リポジトリでも、ログイン済みの本人には表示される）。
"""
import argparse
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()

    date = (dt.date.fromisoformat(args.date) if args.date
            else dt.datetime.now(ZoneInfo("Asia/Tokyo")).date())
    diso = date.isoformat()
    slash = date.strftime("%Y/%m/%d")
    ddir = os.path.join("outputs", diso)

    audit = json.load(open(os.path.join(ddir, "audit.json"), encoding="utf-8"))
    p1 = open(os.path.join(ddir, "post1.txt"), encoding="utf-8").read().rstrip()
    p2 = open(os.path.join(ddir, "post2.txt"), encoding="utf-8").read().rstrip()
    md = open(os.path.join(ddir, "report.md"), encoding="utf-8").read().rstrip()

    sample = audit.get("mode") == "SAMPLE"
    overall = audit.get("overall", "FAIL")
    base = f"https://github.com/{args.repo}/raw/{args.branch}/outputs/{diso}"

    if overall == "PASS":
        title = f"【検収】{slash} Westpac Morning Report"
    else:
        title = f"【FAIL・投稿禁止】{slash} Westpac Morning Report"
    if sample:
        title += "（テスト実行）"

    def metric(gid):
        for g in audit["gates"]:
            if g["id"] == gid:
                return g.get("detail", "")
        return ""

    lines = []
    if overall != "PASS":
        lines += ["> [!CAUTION]",
                  "> 機械検証で不合格のゲートがあります。**このままXへ投稿しないでください。**",
                  "> 下の検証結果を確認し、修正が必要な場合はこのIssueにコメントで指示してください。", ""]
    if sample:
        lines += ["> [!NOTE]",
                  "> これは **サンプルデータによるテスト実行** です。実データではありません。", ""]

    # チャート画像は撮影失敗・サンプル実行時に存在しない。
    # リンク切れの画像を貼らず、状況が分かる文言に差し替える
    if os.path.exists(os.path.join(ddir, "charts_1h.jpg")):
        charts_block = f"![charts]({base}/charts_1h.jpg)"
    elif sample:
        charts_block = "_サンプル実行ではチャートを撮影しないため画像はありません（本番実行では表示されます）。_"
    else:
        charts_block = ("> [!WARNING]\n"
                        "> チャート画像の取得に失敗しました。投稿2にはレポート画像のみ添付してください。")

    lines += [
        f"検証結果: **{overall}** ／ モード: {audit.get('mode')} ／ 生成: {audit.get('verified_at_jst', '')}",
        "",
        "## 1. レポート画像（X投稿2に添付）",
        f"![report]({base}/report_image.png)",
        "",
        "## 2. チャート画像（1H足・参考添付用）",
        charts_block,
        "",
        f"## 3. X投稿1（コピー用｜加重文字数 {metric('I1')}）",
        "```text",
        p1,
        "```",
        "",
        f"## 4. X投稿2（コピー用｜加重文字数 {metric('I2')}）",
        "```text",
        p2,
        "```",
        "",
        "## 5. レポート本文",
        "<details><summary>クリックで全文を表示</summary>",
        "",
        md,
        "",
        "</details>",
        "",
        "## 6. 機械検証ゲート",
        "| ゲート | 判定 | 詳細 |",
        "|---|---|---|",
    ]
    for g in audit["gates"]:
        icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️", "INFO": "ℹ️"}.get(g["status"], "")
        detail = (g.get("detail") or "").replace("|", "／").replace("\n", " ")
        lines.append(f"| {g['id']} {g['name']} | {icon} {g['status']} | {detail} |")
    for w in audit.get("warnings", []):
        lines.append(f"\n> ⚠️ {w}")

    lines += [
        "",
        "## 7. 投稿手順（方式A：手動投稿）",
        "- [ ] 画像2枚と投稿文を確認した",
        "- [ ] 投稿1をXへ投稿した",
        "- [ ] 投稿2をXへ投稿した（レポート画像を添付）",
        "- [ ] このIssueをCloseした（＝投稿完了の記録）",
        "",
        "---",
        f"生成物: `outputs/{diso}/` ／ 元PDF: {json.load(open(os.path.join('sources', diso, 'meta.json'), encoding='utf-8')).get('pdf_url', '(不明)') if os.path.exists(os.path.join('sources', diso, 'meta.json')) else '（サンプルモードのためなし）'}",
        "修正したい場合はこのIssueにコメントを残し、翌日以降の改善に反映します（フェーズ2で再生成コマンドに対応予定）。",
    ]

    with open(os.path.join(ddir, "issue_title.txt"), "w", encoding="utf-8") as f:
        f.write(title)
    with open(os.path.join(ddir, "issue_body.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[build_issue_body] saved: {ddir}/issue_title.txt, issue_body.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
