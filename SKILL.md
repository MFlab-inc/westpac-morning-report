# SKILL: Westpac Morning Report 日次納品（Claude移行版 v2）

Manus用スキルからの主な変更点: ①チャートサイトは実サイト準拠の**8ペア**表記に修正（旧記載の6ペア・US30は誤り） ②レポート画像はAI画像生成ではなく `scripts/render_image.py` による決定論的描画 ③納品先はチャットスレッドではなく**GitHub Issue自動起票**。

## 目的
毎営業日の朝、Westpac IQ Morning Report を情報源として、日本語の市況レポート・X投稿2本・レポート画像・チャート画像の4点を生成し、検収用Issueで納品する。

## 手順（`scripts/run_daily.py` が自動実行）
1. **PDF取得** `scripts/fetch_westpac.py`
   - 必ず https://www.westpaciq.com.au/topic.morningreport から当日リンクを探す（一覧・記事ともJS描画のためPlaywright必須）
   - **PDFのURLを直打ちで推測しない**（月替わりでパスが変わる）
   - 当日分が見つからなければ「未発行」として扱う（8:00→8:20→8:40の3回試行）
2. **チャート撮影** `scripts/capture_charts.py`
   - https://6forex.netlify.app/ を1920×1080で撮影（**8ペア**: USD/JPY・AUD/USD・XAU/USD・EUR/USD・GBP/USD・USD/CAD・USD/CHF・NZD/USD、1H足・表示期間はサイト初期値のまま）
   - 自作チャートでの代替は禁止
3. **本文・投稿生成** `scripts/generate_report.py` ＋ `prompts/generate_prompt.md`
   - 情報源はPDF原文のみ。数値は原文どおり転記
   - レポート本文（3セクション＋イベント表）、投稿1（主要トピック）、投稿2（5ペア通貨別分析）、画像用データを一括生成
4. **レポート画像描画** `scripts/render_image.py`
   - 2560×1440、ダークネイビー（#0A1628）×金（#C9A227）、明朝体
   - 左: 主要テーマ3件（アイコン・見出し・説明2行・影響） 右: 重要ペア3件（大矢印・方向感・根拠・金枠バッジ）
5. **機械検証** `scripts/verify_report.py`（G1〜G8）→ **Issue起票** `scripts/build_issue_body.py`

## 厳守事項
- 分析対象は **USD/JPY・AUD/USD・XAU/USD・EUR/USD・GBP/USD の5ペアのみ**（チャート画像に他ペアが写るのは可）
- **暗号通貨に関する内容は一切禁止**（本文・投稿・画像すべて）
- X投稿に **URLを含めない**（Intent URL含む）
- 出典表記「出典: Westpac IQ Morning Report YYYY/MM/DD」を本文末尾・投稿2・画像フッターに必ず入れる
- 投稿2のペア並び順: #USDJPY → #AUDUSD → #XAUUSD → #EURUSD → #GBPUSD
- 投稿1の固定タグ: #FX #為替 #市況 #ドル円

## 検証ゲート（FAIL時はIssueタイトルに【FAIL・投稿禁止】）
| ID | 内容 |
|---|---|
| G1 | 日付整合（date_jst・本文・投稿2の日付が実行日と一致） |
| G2 | 暗号通貨語の混入ゼロ（日英の禁止語リスト） |
| G3 | 対象5ペア限定（対象外ペアの検出・5タグの存在・画像データの検査） |
| G4 | プレースホルダ残存なし（None/null/{DATE…}等） |
| G5 | 出典表記の存在 |
| G6 | 規定ハッシュタグの存在 |
| G7 | 投稿にURLなし |
| G8 | 投稿2の数値がPDF原文に存在（カンマ正規化のうえ照合。サンプル実行時はSKIP） |

## 運用モード
- 方式A（現行）: Issueで検収 → ユーザーが手動でX投稿 → Close
- 方式B（フェーズ2）: Issueへの「承認」コメントでX APIによる自動投稿（HANDOFF参照）
