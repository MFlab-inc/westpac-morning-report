#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_event_times.py — イベント表の時刻をプログラムで換算する処理（event_times.py）のテスト。

実行: python3 -I tests/test_event_times.py
（pytest等の追加依存を避け、標準ライブラリのunittestのみを使う）

AIが換算していた間の誤りの実例（いずれも G9 で FAIL）:
  - 2026-10-29: 原文 20:30 の英国の指標 → 正 18:30 を 18:00 と記載
  - 2026-11-09: 原文 2:00・3:00 → 正 0:00(翌日)・1:00(翌日) を 23:00・0:00 と記載
  - 2026-11-17: 原文 0:30・2:00 → 正 22:30・0:00(翌日) を 23:30・1:00(翌日) と記載
  - 2026-11-26: 原文 11:30 の豪州民間設備投資 → 正 9:30 を 10:30 と記載
"""
import datetime as dt
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import event_times as et  # noqa: E402
import verify_report as vr  # noqa: E402

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def src_table(*rows):
    """原文のイベント表の簡約版（見出し〜"Times are AEST." まで）"""
    return ("Today's key data and events\nTime Event Exp Prev\n" + "\n".join(rows)
            + "\nTimes are AEST. All data forecasts are m/m\n")


def read_source(date_str):
    p = os.path.join(REPO_ROOT, "sources", date_str, "westpac.txt")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else None


class DayOffsetTest(unittest.TestCase):
    def test_midnight_crossing(self):
        # 2026-11-17 の並び: 夜の 21:00 の次に 0:30 へ戻る → そこから翌日
        times = ["08:45", "11:30", "21:00", "00:30", "00:30", "02:00"]
        self.assertEqual(et.day_offsets(times), [0, 0, 0, 1, 1, 1])

    def test_table_starting_after_midnight(self):
        # 2026-10-07: 表が深夜0時以降の行だけ（2:00・6:00）
        self.assertEqual(et.day_offsets(["02:00", "06:00"]), [1, 1])

    def test_morning_7am_is_same_day(self):
        # 2026-10-02: 先頭の 7:00 はニュージーランドの朝の指標（当日）
        self.assertEqual(et.day_offsets(["07:00", "09:30", "22:30", "00:00"]), [0, 0, 0, 1])

    def test_late_7am_after_crossing_is_next_day(self):
        # 2026-11-06: 米消費者信用（7:00 AEDT）は深夜0時をまたいだ後なので翌日
        self.assertEqual(et.day_offsets(["21:00", "00:30", "02:00", "07:00"]), [0, 1, 1, 1])


class ToJstTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(et.to_jst(11 * 60 + 30, 0, 2)[1], "9:30")
        self.assertEqual(et.to_jst(30, 1, 2)[1], "22:30")          # 翌0:30 AEDT → 当日22:30 JST
        self.assertEqual(et.to_jst(2 * 60, 1, 2)[1], "0:00(翌日)")
        self.assertEqual(et.to_jst(0, 1, 1)[1], "23:00")           # 夏時間でない時期（1時間）


class RenderTableTest(unittest.TestCase):
    SRC_1126 = src_table("11:30 AU Private New Capital Expenditure Q3 4.2% -3.6%",
                         "20:00 EZ M3 Money Supply Oct 3.5% 3.5%",
                         "- US Thanksgiving Holiday", "- SK Bank of Korea Policy Decision 3.25% 3.00%")
    EVENTS_1126 = [
        {"src_time": "11:30", "country": "AU", "event": "民間設備投資 Q3", "exp": "4.2%", "prev": "-3.6%"},
        {"src_time": "20:00", "country": "EZ", "event": "M3マネーサプライ 10月", "exp": "3.5%", "prev": "3.5%"},
        {"src_time": "-", "country": "US", "event": "感謝祭（休場）", "exp": "-", "prev": "-"},
        {"src_time": "-", "country": "SK", "event": "韓国銀行 政策金利", "exp": "3.25%", "prev": "3.00%"},
    ]

    def test_2026_11_26_case(self):
        table, notes = et.render_event_table(self.EVENTS_1126, self.SRC_1126, 2)
        lines = table.splitlines()
        self.assertEqual(lines[0], "| 時刻(JST) | 国 | イベント | 予想 | 前回 |")
        self.assertTrue(lines[2].startswith("| 9:30 | AU | 民間設備投資 Q3 |"), lines[2])
        self.assertTrue(lines[3].startswith("| 18:00 | EZ |"), lines[3])
        self.assertTrue(lines[4].startswith("| - | US |"), lines[4])   # 時刻の無い行は末尾・元の順
        self.assertTrue(lines[5].startswith("| - | SK |"), lines[5])
        self.assertEqual(notes, [])

    def test_sorted_by_jst_with_next_day_mark(self):
        src = src_table("08:45 NZ a", "21:00 GB b", "00:30 US c", "02:00 US d")
        events = [{"src_time": t, "country": "X", "event": n, "exp": "-", "prev": "-"}
                  for t, n in (("02:00", "d"), ("00:30", "c"), ("08:45", "a"), ("21:00", "b"))]
        table, _ = et.render_event_table(events, src, 2)
        times = [ln.split("|")[1].strip() for ln in table.splitlines()[2:]]
        self.assertEqual(times, ["6:45", "19:00", "22:30", "0:00(翌日)"])

    def test_time_not_in_source_is_noted(self):
        events = [{"src_time": "03:00", "country": "US", "event": "x", "exp": "-", "prev": "-"}]
        table, notes = et.render_event_table(events, src_table("11:30 AU a"), 2)
        self.assertIn("1:00(翌日)", table)
        self.assertEqual(len(notes), 1)

    def test_empty_events(self):
        table, notes = et.render_event_table([], self.SRC_1126, 2)
        self.assertEqual(notes, ["events が空"])

    def test_pipe_in_text_does_not_break_table(self):
        events = [{"src_time": "11:30", "country": "AU", "event": "a|b", "exp": "-", "prev": "-"}]
        table, _ = et.render_event_table(events, src_table("11:30 AU a"), 2)
        self.assertEqual(table.splitlines()[2].count("|"), 6)

    def test_time_map_text(self):
        self.assertEqual(et.time_map_text(self.SRC_1126, 2), "11:30→9:30、20:00→18:00")
        self.assertIn("読み取れなかった", et.time_map_text("no table here", 2))


class AllPastDaysTest(unittest.TestCase):
    """過去の全営業日の原文で、原文の時刻を写した events から作った表が G9 の期待値と
    一致することを確認する（AIが時刻を正しく写せば G9 は必ず PASS する）。
    outputs/・sources/ は読むだけで、書き換えない。"""

    def test_matches_g9_expectation(self):
        paths = sorted(glob.glob(os.path.join(REPO_ROOT, "sources", "*", "westpac.txt")))
        if not paths:
            self.skipTest("sources/ がこの環境には存在しない")
        checked = 0
        for p in paths:
            date_str = os.path.basename(os.path.dirname(p))
            src = open(p, encoding="utf-8").read()
            window = vr.find_event_table_window(src)
            times = et.source_times(src)
            if window is None or not times:
                continue
            shift = vr.tz_shift_hours(dt.date.fromisoformat(date_str))
            events = [{"src_time": t, "country": "X", "event": f"e{i}", "exp": "-", "prev": "-"}
                      for i, t in enumerate(times)]
            table, notes = et.render_event_table(events, src, shift)
            self.assertEqual(vr.times_in(table), vr.shift_times(vr.times_in(window), shift), date_str)
            self.assertEqual(notes, [], date_str)
            checked += 1
        self.assertGreater(checked, 0)

    def test_2026_11_26_real_source(self):
        src = read_source("2026-11-26")
        if src is None:
            self.skipTest("2026-11-26 のデータがこの環境には存在しない")
        self.assertEqual(et.time_map_text(src, 2), "11:30→9:30、20:00→18:00")


if __name__ == "__main__":
    unittest.main()
