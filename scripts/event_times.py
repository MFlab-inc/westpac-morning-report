#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
event_times.py — 原文のイベント表の時刻を日本時間（JST）に換算し、report_md の
「## 3. 本日の重要イベント」の表をプログラムで作る。

背景: 時刻の換算をAIに任せていた間、PR #113 で生成ルールを直した後も誤りが続いた
（2026-10-29・11-09・11-17・11-26。毎回パターンが違い、行ごとに引く時間数を
取り違えた）。そこで AI には原文の時刻をそのまま写させ（events[].src_time）、
換算・並べ替え・「(翌日)」の付与はここで行う。検証ゲート G9 は従来どおり、
原文の時刻から計算した期待値と report.md の表を照合する。

日付の判定（シドニーの当日か、深夜0時を過ぎた翌日か）:
  原文の表は、シドニーの朝の指標から米国の深夜の指標まで時系列順に並んでいる
  （2026-09-25〜11-26 の43営業日すべてで確認。深夜0時をまたぐ戻りは最大1回）。
  そこで、表の中で時刻が前の行より戻ったところから先を翌日とみなす。
  表が深夜0時以降の行だけで始まる日（実例: 2026-10-07 の 2:00・6:00）のため、
  先頭の行が 7:00 より前なら最初から翌日とみなす。7:00 ちょうどは当日の朝
  （実例: 2026-10-02 のニュージーランドの指標 7:00 AEST）として扱う。
"""
import re

from verify_report import find_event_table_window   # G9 と同じ見出しの探し方を使う

_TIME_RE = re.compile(r"(?<!\d)([0-2]?\d):([0-5]\d)(?!\d)")
FIRST_ROW_NEXT_DAY_BEFORE = 7 * 60   # 先頭の行がこれ（分）より前なら翌日とみなす


def _minutes(hhmm: str):
    m = _TIME_RE.search(str(hhmm))
    if not m or int(m.group(1)) > 23:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def source_times(src_text: str) -> list:
    """原文の「Today's key data and events」の表の時刻を、記載順に返す（"HH:MM"）。"""
    window = find_event_table_window(src_text or "")
    if window is None:
        return []
    return [f"{int(h):02d}:{m}" for h, m in _TIME_RE.findall(window) if int(h) <= 23]


def day_offsets(times: list) -> list:
    """各時刻がシドニーの当日(0)か翌日(1)かを、表の並び順から決める。"""
    out, offset, prev = [], 0, None
    for i, t in enumerate(times):
        m = _minutes(t)
        if i == 0 and m < FIRST_ROW_NEXT_DAY_BEFORE:
            offset = 1
        elif prev is not None and m < prev:
            offset = 1
        out.append(offset)
        prev = m
    return out


def offset_map(src_text: str) -> dict:
    """原文の時刻 → 当日(0)/翌日(1)。同じ時刻が2回出たら最初のものを使う。"""
    times = source_times(src_text)
    out = {}
    for t, off in zip(times, day_offsets(times)):
        out.setdefault(t, off)
    return out


def to_jst(src_minutes: int, day_offset: int, shift_hours: int):
    """(並べ替え用の分, 表示) を返す。表示は「9:30」「0:00(翌日)」の形。"""
    total = day_offset * 1440 + src_minutes - shift_hours * 60
    jday, rest = divmod(total, 1440)
    suffix = {0: "", 1: "(翌日)", -1: "(前日)"}.get(jday, "")
    return total, f"{rest // 60}:{rest % 60:02d}{suffix}"


def time_map_text(src_text: str, shift_hours: int) -> str:
    """プロンプトに入れる「原文の時刻→日本時間」の対応（原文の記載順・重複なし）。"""
    times = source_times(src_text)
    if not times:
        return "（原文のイベント表から時刻を読み取れなかった）"
    pairs, seen = [], set()
    for t, off in zip(times, day_offsets(times)):
        if t in seen:
            continue
        seen.add(t)
        src_label = f"{int(t[:2])}:{t[3:]}"
        pairs.append(f"{src_label}→{to_jst(_minutes(t), off, shift_hours)[1]}")
    return "、".join(pairs)


def _cell(value) -> str:
    s = str(value if value is not None else "").strip() or "-"
    return s.replace("|", "／").replace("\n", " ")


def render_event_table(events, src_text: str, shift_hours: int):
    """events（AIが原文から写した行）から Markdown 表を作る。(表, 注記のリスト) を返す。

    - 時刻は src_time から計算する（AIが書いた日本時間は使わない）
    - 時刻順に並べ、時刻の無い行（"-"）は末尾に元の順で置く
    - src_time が原文の表に見つからない場合は、7:00 より前を翌日とみなして換算し、注記に残す
    """
    notes = []
    if not isinstance(events, list) or not events:
        return "原文のイベント表から行を作れなかった（events が空）。", ["events が空"]
    offsets = offset_map(src_text)
    timed, untimed = [], []
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            notes.append(f"{i + 1}行目の形式が不正のため除外")
            continue
        src_min = _minutes(ev.get("src_time", ""))
        row = [_cell(ev.get("country")), _cell(ev.get("event")), _cell(ev.get("exp")), _cell(ev.get("prev"))]
        if src_min is None:
            untimed.append(["-"] + row)
            continue
        key = _hhmm(src_min)
        if key in offsets:
            off = offsets[key]
        else:
            off = 1 if src_min < FIRST_ROW_NEXT_DAY_BEFORE else 0
            notes.append(f"原文の表に無い時刻 {key}（{row[1]}）を{'翌日' if off else '当日'}として換算")
        total, label = to_jst(src_min, off, shift_hours)
        timed.append((total, i, [label] + row))
    timed.sort(key=lambda x: (x[0], x[1]))
    lines = ["| 時刻(JST) | 国 | イベント | 予想 | 前回 |", "|---|---|---|---|---|"]
    lines += ["| " + " | ".join(r) + " |" for _, _, r in timed]
    lines += ["| " + " | ".join(r) + " |" for r in untimed]
    return "\n".join(lines), notes
