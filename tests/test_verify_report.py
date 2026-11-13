#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_verify_report.py — G9（イベント時刻JST換算チェック）・G11（通貨ペア方向感照合）
のregex回帰テスト。

実行: python3 -I tests/test_verify_report.py
（pytest等の追加依存を避け、標準ライブラリのunittestのみを使う）

対象の実例:
  - 2026-10-28: 見出し探索が原文の要約文中の類似フレーズ
    （"ahead of today's key data and central bank decisions"）に誤って
    当たり、本来のイベント表より前で窓を切り出してしまっていた。
  - 2026-10-22: 「翌0:00」のように時刻の直前が日本語の文字（Unicodeの
    単語構成文字）の場合、\\b（Unicode単語境界）が効かず時刻を読み落として
    いた。
  - 2026-11-12: GBP/USDの向きを、AUD/USD -0.2%・AUD/GBP +0.3%から
    「AUD/USDの変化−AUD/GBPの変化」ではなく逆向きに計算し、本来下落
    （約-0.5%）のところを上昇と判定していた。G1〜G10では検出できなかった。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import verify_report as vr  # noqa: E402

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


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


class TableChangePctTest(unittest.TestCase):
    def test_reads_table_row(self):
        text = "AUD/USD 0.6850 -0.2% 90 day BBSY 4.99 0.01"
        self.assertEqual(vr.table_change_pct(text, "AUD/USD"), -0.2)

    def test_does_not_match_prose_mention(self):
        # "Gold prices meanwhile dipped 1.2%" は "Gold <値> <%>" の並びでは
        # ないため、表の行と誤認しない
        text = "Gold prices meanwhile dipped 1.2%, extending losses."
        self.assertIsNone(vr.table_change_pct(text, "Gold"))

    def test_missing_label_returns_none(self):
        self.assertIsNone(vr.table_change_pct("nothing here", "EUR/USD"))


class SignDirTest(unittest.TestCase):
    def test_sign_dir(self):
        self.assertEqual(vr.sign_dir(0.3), "up")
        self.assertEqual(vr.sign_dir(-0.2), "down")
        self.assertEqual(vr.sign_dir(0.0), "flat")


class GbpDirectStatementTest(unittest.TestCase):
    def test_simple_direct_statement(self):
        # 2026-10-19実例の簡約版（2段組PDF由来で改行をまたぐ）
        text = "more subdued with the yen flat, the euro losing 0.3% and the\npound down 0.1%."
        direction, quote = vr.gbp_direct_statement(text)
        self.assertEqual(direction, "down")
        self.assertIn("pound", quote)

    def test_shared_subject_with_another_currency_is_ambiguous(self):
        # "Sterling and Loonie fell 0.2% and 0.4% respectively" はどちらの%が
        # ポンドのものか文字列だけでは特定できないため採用しない
        text = "Sterling and Loonie fell 0.2% and 0.4% respectively against the greenback."
        self.assertEqual(vr.gbp_direct_statement(text), (None, None))

    def test_no_percentage_is_ambiguous(self):
        text = "The sterling added to its recent gains against the greenback."
        self.assertEqual(vr.gbp_direct_statement(text), (None, None))

    def test_flat_without_percentage_is_accepted(self):
        text = "the euro was flat and the pound flat against the greenback."
        direction, _ = vr.gbp_direct_statement(text)
        self.assertEqual(direction, "flat")

    def test_returns_none_when_absent(self):
        self.assertEqual(vr.gbp_direct_statement("no mention of currencies here"), (None, None))


class ExpectedPairDirectionsTest(unittest.TestCase):
    def test_gbp_cross_below_threshold_is_not_judged(self):
        # AUD/USD 0.0%・AUD/GBP +0.1% → 計算値-0.1%は閾値0.15%未満のため
        # GBP/USDを判定しない（実例: 2026-09-23・2026-11-02）
        text = "AUD/USD 0.7030 0.0% 90 day BBSY\nAUD/GBP 0.5260 0.1% 1 year swap"
        out = vr.expected_pair_directions(text)
        self.assertNotIn("GBP/USD", out)

    def test_gbp_cross_above_threshold_is_judged(self):
        # 2026-11-12実例: AUD/USD -0.2%・AUD/GBP +0.3% → 約-0.5%（下落）
        text = "AUD/USD 0.6850 -0.2% 90 day BBSY\nAUD/GBP 0.5159 0.3% 1 year swap"
        out = vr.expected_pair_directions(text)
        self.assertEqual(out["GBP/USD"][0], "down")

    def test_direct_statement_overrides_cross_calculation(self):
        # 2026-10-19実例の簡約版: 直接記述は下落だが、クロス計算は符号が逆
        # （AUD/USD+0.7%・AUD/GBP+0.4% → 計算は約+0.3%・上昇）になる。
        # 厳守事項13と同じ優先順位で直接記述を正とする。
        text = (
            "AUD/USD 0.6969 0.7% 90 day BBSY\n"
            "AUD/GBP 0.5233 0.4% 1 year swap\n"
            "more subdued with the yen flat, the euro losing 0.3% and the\n"
            "pound down 0.1%."
        )
        out = vr.expected_pair_directions(text)
        self.assertEqual(out["GBP/USD"][0], "down")
        self.assertIn("直接記述", out["GBP/USD"][1])

    def test_other_pairs_from_tables(self):
        text = "USD/JPY 158.32 0.0% x\nAUD/USD 0.6973 -0.2% x\nEUR/USD 1.12 -0.6% x\nGold 4102.98 -1.4% x"
        out = vr.expected_pair_directions(text)
        self.assertEqual(out["USD/JPY"][0], "flat")
        self.assertEqual(out["AUD/USD"][0], "down")
        self.assertEqual(out["EUR/USD"][0], "down")
        self.assertEqual(out["XAU/USD"][0], "down")


class PairDirExtractionTest(unittest.TestCase):
    def test_post2_pair_dir_with_value(self):
        p2 = "#USDJPY 158.32 → ほぼ横ばい\n根拠：..."
        self.assertEqual(vr.post2_pair_dir(p2, "USD/JPY"), "flat")

    def test_post2_pair_dir_without_value(self):
        p2 = "#GBPUSD ↑ ポンド底堅い\n根拠：..."
        self.assertEqual(vr.post2_pair_dir(p2, "GBP/USD"), "up")

    def test_report_md_pair_dir(self):
        md = "### GBP/USD ― 上昇（↑）\n本文..."
        self.assertEqual(vr.report_md_pair_dir(md, "GBP/USD"), "up")

    def test_pairs_image_pair_dir(self):
        data = {"pairs_image": [{"pair": "XAU/USD", "dir": "down"}]}
        self.assertEqual(vr.pairs_image_pair_dir(data, "XAU/USD"), "down")
        self.assertIsNone(vr.pairs_image_pair_dir(data, "GBP/USD"))


class G11RealDataRegressionTest(unittest.TestCase):
    """2026-11-12（誤り実例）・2026-10-19（直接記述優先の正しい例）の実データで
    G11の判定を確認する。outputs/・sources/ は読むだけで、一切書き換えない。
    """

    def _mismatches(self, date_str):
        src_path = os.path.join(REPO_ROOT, "sources", date_str, "westpac.txt")
        md_path = os.path.join(REPO_ROOT, "outputs", date_str, "report.md")
        p2_path = os.path.join(REPO_ROOT, "outputs", date_str, "post2.txt")
        data_path = os.path.join(REPO_ROOT, "outputs", date_str, "report_data.json")
        if not all(os.path.exists(p) for p in (src_path, md_path, p2_path, data_path)):
            self.skipTest(f"{date_str} のデータがこの環境には存在しない")
        src_text = open(src_path, encoding="utf-8").read()
        md = open(md_path, encoding="utf-8").read()
        p2 = open(p2_path, encoding="utf-8").read()
        data = json.load(open(data_path, encoding="utf-8"))
        expected = vr.expected_pair_directions(src_text)
        mismatches = []
        for pair, (edir, basis) in expected.items():
            for loc, actual in (
                ("post2", vr.post2_pair_dir(p2, pair)),
                ("report.md", vr.report_md_pair_dir(md, pair)),
                ("pairs_image", vr.pairs_image_pair_dir(data, pair)),
            ):
                if actual is not None and actual != edir:
                    mismatches.append((pair, loc, edir, actual, basis))
        return mismatches

    def test_2026_11_12_fails(self):
        mismatches = self._mismatches("2026-11-12")
        self.assertTrue(any(m[0] == "GBP/USD" for m in mismatches),
                         f"2026-11-12はGBP/USDの向き誤りを検出するはず: {mismatches}")

    def test_2026_10_19_passes(self):
        mismatches = self._mismatches("2026-10-19")
        self.assertEqual(mismatches, [], f"2026-10-19は全ペア一致するはず: {mismatches}")


if __name__ == "__main__":
    unittest.main()
