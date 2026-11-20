#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_render_image.py — レポート画像レンダラー（v3・案A2）のテスト。

実行: python3 -I tests/test_render_image.py
（pytest等の追加依存を避け、標準ライブラリのunittestのみを使う）

- 数値ボックスのレート・変化率は、AIの出力ではなく原文の表から読み取る（table_quote）
- 表に数値が無いペア（GBP/USD）は None を返し、画像では方向ラベルのみを表示する
- 描画の通し確認は日本語フォント（fonts-noto-cjk）がある環境でのみ実行する
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import render_image as ri  # noqa: E402

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

TABLE = (
    "FX Last 24 hrs Current Change AUS Interest Rate Swaps Last Change\n"
    "further Fed tightening, while AUD/USD 0.6711 -0.4% 90 day BBSY 5.00 0.01\n"
    "AUD/GBP 0.5107 0.1% 1 year swap 4.94 -0.01\n"
    "EUR/USD 1.0965 -0.3% 8 year swap 4.91 -0.05\n"
    "USD/JPY 159.35 0.0% 9 year swap 4.96 -0.05\n"
    "Gold 3720.74 -3.3% UK 5.29 -0.08\n"
)


class TableQuoteTest(unittest.TestCase):
    def test_reads_value_and_change_as_written(self):
        self.assertEqual(ri.table_quote(TABLE, "AUD/USD"), ("0.6711", "-0.4"))
        self.assertEqual(ri.table_quote(TABLE, "USD/JPY"), ("159.35", "0.0"))
        self.assertEqual(ri.table_quote(TABLE, "EUR/USD"), ("1.0965", "-0.3"))

    def test_gold_gets_thousands_separator(self):
        self.assertEqual(ri.table_quote(TABLE, "XAU/USD"), ("3,720.74", "-3.3"))

    def test_pair_without_table_row(self):
        self.assertIsNone(ri.table_quote(TABLE, "GBP/USD"))

    def test_no_source(self):
        self.assertIsNone(ri.table_quote(None, "USD/JPY"))

    def test_direction_from_change(self):
        self.assertEqual(ri.pct_direction("-0.4"), "down")
        self.assertEqual(ri.pct_direction("0.0"), "flat")
        self.assertEqual(ri.pct_direction("0.2"), "up")

    def test_real_2026_11_19_source(self):
        src_path = os.path.join(REPO_ROOT, "sources", "2026-11-19", "westpac.txt")
        if not os.path.exists(src_path):
            self.skipTest("2026-11-19 のデータがこの環境には存在しない")
        src_text = open(src_path, encoding="utf-8").read()
        self.assertEqual(ri.table_quote(src_text, "XAU/USD"), ("3,720.74", "-3.3"))
        self.assertEqual(ri.table_quote(src_text, "AUD/USD"), ("0.6711", "-0.4"))


class SplitTwoLinesTest(unittest.TestCase):
    def _font(self):
        try:
            return ri.font("black", 52)
        except RuntimeError:
            self.skipTest("日本語フォントが無い環境")

    def test_breaks_after_particle(self):
        f = self._font()
        lines = ri.split_two_lines("米中露首脳三者会談に注目集まる", f, 600)
        self.assertEqual(lines, ["米中露首脳三者会談に", "注目集まる"])

    def test_single_line_when_it_fits(self):
        f = self._font()
        self.assertEqual(ri.split_two_lines("金急落", f, 600), ["金急落"])


class RenderSmokeTest(unittest.TestCase):
    """サンプルデータ（headline・alertあり）と、headline・alertが無い旧形式の両方で
    最後まで描画でき、2560x1440のPNGになることを確認する。"""

    def _data(self):
        path = os.path.join(REPO_ROOT, "sample_data", "report_data_sample.json")
        return json.load(open(path, encoding="utf-8"))

    def _render(self, data, src_text):
        try:
            ri.font("black", 40)
        except RuntimeError:
            self.skipTest("日本語フォントが無い環境")
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "img.png")
            ri.render(data, out, src_text)
            with Image.open(out) as im:
                self.assertEqual(im.size, (2560, 1440))

    def test_sample_with_source_table(self):
        self._render(self._data(), TABLE)

    def test_without_headline_alert_and_source(self):
        data = self._data()
        data.pop("headline", None)
        data.pop("alert", None)
        self._render(data, None)


if __name__ == "__main__":
    unittest.main()
