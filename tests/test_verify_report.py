#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_verify_report.py — G9（イベント時刻JST換算チェック）のregex回帰テスト。

実行: python3 -I tests/test_verify_report.py
（pytest等の追加依存を避け、標準ライブラリのunittestのみを使う）

対象の実例:
  - 2026-10-28: 見出し探索が原文の要約文中の類似フレーズ
    （"ahead of today's key data and central bank decisions"）に誤って
    当たり、本来のイベント表より前で窓を切り出してしまっていた。
  - 2026-10-22: 「翌0:00」のように時刻の直前が日本語の文字（Unicodeの
    単語構成文字）の場合、\\b（Unicode単語境界）が効かず時刻を読み落として
    いた。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import verify_report as vr  # noqa: E402


class FindEventTableWindowTest(unittest.TestCase):
    def test_skips_decoy_phrase_before_real_heading(self):
        # 2026-10-28実例の簡約版：1ページ目の要約欄に見出しと紛らわしい文があり、
        # 本来の見出し（"Today's key data and events"）はそのあとに続く。
        src_text = (
            "Equities Close Change\n"
            "Attention now turns to a series of key economic developments, "
            "with Australian CPI due today ahead of today’s key data and "
            "central bank decisions.\n"
            "S&P/ASX 200 8,850 0.5% Australia\n"
            "\n"
            "TODAY’S INSIGHTS\n"
            "Today’s key data and events\n"
            "Time Event Exp Prev\n"
            "11:30 AU Monthly CPI Indicator Sep 4.2% 4.0%\n"
            "23:30 US Wholesale Inventories Sep Prel. 0.5% 0.5%\n"
            "Times are AEST.\n"
        )
        window = vr.find_event_table_window(src_text)
        self.assertIsNotNone(window)
        self.assertTrue(window.startswith("Today’s key data and events"))
        self.assertEqual(vr.times_in(window), {"11:30", "23:30"})

    def test_returns_none_when_no_heading(self):
        self.assertIsNone(vr.find_event_table_window("no event table here at all"))

    def test_cuts_off_at_times_are_line(self):
        src_text = (
            "Today’s key data and events\n"
            "11:30 AU Test Event A B\n"
            "Times are AEST. All data forecasts are m/m or q/q.\n"
            "This trailing paragraph should not be included: 9:99 is not a real time."
        )
        window = vr.find_event_table_window(src_text)
        self.assertIn("Times are AEST.", window)
        self.assertNotIn("trailing paragraph", window)


class TimesInTest(unittest.TestCase):
    def test_reads_time_directly_after_japanese_character(self):
        # 2026-10-22実例：表の「翌0:00」列。直前が日本語の文字（翌）で、
        # 旧実装の \b では境界と認識されず読み落としていた。
        text = "| 翌0:00 | 米 | カンザスシティ連銀製造業景気指数（10月） | 12pts | 14pts |"
        self.assertEqual(vr.times_in(text), {"00:00"})

    def test_reads_multiple_japanese_prefixed_times(self):
        text = "翌0:00 と 翌1:30 の2件"
        self.assertEqual(vr.times_in(text), {"00:00", "01:30"})

    def test_still_reads_space_separated_day_marker(self):
        # 既存の表記（例: "3:00(翌日)"・"21:30 (前日)"）は前後に空白や括弧があり、
        # 旧実装でも正しく読めていたため、回帰していないことを確認する。
        text = "| 3:00(翌日) | US | FOMC政策金利決定 | 3.875% | 3.875% |\n| 21:30 (前日) | 米国 | 指標名 | - | - |"
        self.assertEqual(vr.times_in(text), {"03:00", "21:30"})

    def test_ignores_dash_rows_without_time(self):
        text = "| - | AU | 指標名 | 予想なし | - |"
        self.assertEqual(vr.times_in(text), set())

    def test_does_not_match_slash_separated_date(self):
        text = "FOMC政策金利決定（2026/10/28） 3.875%"
        self.assertEqual(vr.times_in(text), set())

    def test_hour_above_23_ignored(self):
        # 時 2桁が24以上になるケース（\dの範囲上限 [0-2]? の外）は対象外
        self.assertEqual(vr.times_in("99:30"), set())


class ShiftTimesTest(unittest.TestCase):
    def test_simple_shift(self):
        self.assertEqual(vr.shift_times({"11:30"}, 2), {"09:30"})

    def test_wraps_to_previous_day(self):
        self.assertEqual(vr.shift_times({"01:00"}, 2), {"23:00"})

    def test_multiple_times(self):
        self.assertEqual(
            vr.shift_times({"11:30", "23:30", "00:45"}, 2),
            {"09:30", "21:30", "22:45"},
        )


if __name__ == "__main__":
    unittest.main()
