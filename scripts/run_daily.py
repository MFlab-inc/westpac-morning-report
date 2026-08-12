#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_daily.py — 日次パイプラインのオーケストレータ（GitHub Actionsから呼び出し）。

環境変数:
  WMR_SAMPLE = "true" でサンプルモード（Westpac取得・API・チャート撮影をスキップ）
  WMR_FINAL  = "true" で当日の最終試行（未発行・エラーをIssueで通知する）
  WMR_MANUAL = "true" で手動実行（最終試行と同様に必ず結果を通知する）
  WMR_DATE   = 対象日の上書き（YYYY-MM-DD、通常は未設定）

GITHUB_OUTPUT に publish / date / title_path / body_path を書き出す。
このスクリプト自体は原則 exit 0（インフラ異常時のみ非0）。
"""
import datetime as dt
import json
import os
import subprocess
import sys
import shutil
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def env_true(name):
    return os.environ.get(name, "").strip().lower() in ("true", "1", "yes")


def log(msg):
    print(f"[run_daily] {msg}", flush=True)


def run(script, *args):
    cmd = [PY, os.path.join(HERE, script), *args]
    log("$ " + " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(p.stdout)
    sys.stderr.write(p.stderr)
    return p.returncode, (p.stdout + "\n" + p.stderr)[-4000:]


def gh_output(**kv):
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        for k, v in kv.items():
            log(f"(no GITHUB_OUTPUT) {k}={v}")
        return
    with open(path, "a", encoding="utf-8") as f:
        for k, v in kv.items():
            f.write(f"{k}={v}\n")


def write_notice(ddir, title, body_lines):
    os.makedirs(ddir, exist_ok=True)
    with open(os.path.join(ddir, "issue_title.txt"), "w", encoding="utf-8") as f:
        f.write(title)
    with open(os.path.join(ddir, "issue_body.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(body_lines))


def prune_old(days=60):
    cutoff = dt.date.today() - dt.timedelta(days=days)
    for root in ("outputs", "sources"):
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            try:
                d = dt.date.fromisoformat(name)
            except ValueError:
                continue
            if d < cutoff:
                shutil.rmtree(os.path.join(root, name), ignore_errors=True)
                log(f"pruned: {root}/{name}")


def main():
    sample = env_true("WMR_SAMPLE")
    final = env_true("WMR_FINAL") or env_true("WMR_MANUAL")
    date = (dt.date.fromisoformat(os.environ["WMR_DATE"]) if os.environ.get("WMR_DATE")
            else dt.datetime.now(ZoneInfo("Asia/Tokyo")).date())
    diso = date.isoformat()
    slash = date.strftime("%Y/%m/%d")
    ddir = os.path.join("outputs", diso)
    log(f"date={diso} sample={sample} final_or_manual={final}")

    # 重複ガード（同日の後続cronは何もしない）
    if os.path.exists(os.path.join(ddir, "audit.json")):
        log("本日分は生成済み。スキップします")
        gh_output(publish="false", date=diso)
        return 0

    notify = final  # 未発行・エラー通知は最終試行/手動時のみ

    if not sample:
        rc, tail = run("fetch_westpac.py", "--date", diso)
        if rc == 3:
            log("当日分は未発行")
            if notify:
                write_notice(ddir, f"【未発行】{slash} Westpac Morning Report", [
                    "> [!WARNING]",
                    f"> 8:00〜8:40 JSTの全試行で当日のMorning Reportを確認できませんでした。",
                    "",
                    "考えられる理由: 豪州の祝日 / 発行遅延 / サイト構造の変更。",
                    "",
                    "対応:",
                    "- 祝日・休刊の場合: このIssueをCloseしてください（本日の配信はありません）。",
                    "- 発行が遅れているだけの場合: ActionsのRun workflowから手動で再実行できます。",
                    "- 連日発生する場合: `sources/` のdebugファイルを添えてClaude Codeに調査を依頼してください。",
                ])
                gh_output(publish="true", date=diso,
                          title_path=f"{ddir}/issue_title.txt", body_path=f"{ddir}/issue_body.md")
            else:
                gh_output(publish="false", date=diso)
            return 0
        if rc != 0:
            log(f"fetchが異常終了 rc={rc}")
            if notify:
                write_notice(ddir, f"【エラー】{slash} 取得工程で失敗", [
                    "> [!CAUTION]",
                    f"> fetch_westpac.py が exit code {rc} で失敗しました。",
                    "", "```", tail.strip(), "```", "",
                    "`sources/` 配下のdebugファイルとこのログを添えてClaude Codeに調査を依頼してください。",
                ])
                gh_output(publish="true", date=diso,
                          title_path=f"{ddir}/issue_title.txt", body_path=f"{ddir}/issue_body.md")
            else:
                gh_output(publish="false", date=diso)
            return 0

        rc, _ = run("capture_charts.py", "--date", diso)
        if rc != 0:
            log("チャート撮影に失敗（続行し、Issueで目視確認）")

    # 生成 → 描画 → 検証 → Issue本文
    steps = [
        ("generate_report.py", ["--date", diso] + (["--sample"] if sample else [])),
        ("render_image.py", ["--data", f"{ddir}/report_data.json",
                             "--out", f"{ddir}/report_image.png"]),
    ]
    for script, sargs in steps:
        rc, tail = run(script, *sargs)
        if rc != 0:
            log(f"{script} が失敗 rc={rc}")
            if notify:
                write_notice(ddir, f"【エラー】{slash} 生成工程で失敗", [
                    "> [!CAUTION]",
                    f"> {script} が exit code {rc} で失敗しました。本日の納品はありません。",
                    "", "```", tail.strip(), "```", "",
                    "このログを添えてClaude Codeに調査を依頼してください。",
                ])
                gh_output(publish="true", date=diso,
                          title_path=f"{ddir}/issue_title.txt", body_path=f"{ddir}/issue_body.md")
            else:
                gh_output(publish="false", date=diso)
            return 0

    run("verify_report.py", "--date", diso)          # PASS/FAILどちらでも納品して人が判断
    rc, tail = run("build_issue_body.py", "--date", diso)
    if rc != 0:
        write_notice(ddir, f"【エラー】{slash} Issue本文の生成に失敗", [
            "> [!CAUTION]", f"> build_issue_body.py が失敗しました。", "",
            "```", tail.strip(), "```"])

    prune_old(60)
    gh_output(publish="true", date=diso,
              title_path=f"{ddir}/issue_title.txt", body_path=f"{ddir}/issue_body.md")
    log("完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
