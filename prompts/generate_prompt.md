あなたは機関投資家向け市況レポートの編集者です。以下のWestpac IQ Morning Report（{DATE_ISO} 発行）の原文テキストだけを情報源として、日本語の朝レポート一式をJSONで作成してください。

# 厳守事項（違反は納品不可）
1. 情報源は下記のPDF原文のみ。原文にない事実・数値を推測で補完しない。不明な値は「未確認」と書く。
2. 通貨ペア分析の対象は USD/JPY・AUD/USD・XAU/USD・EUR/USD・GBP/USD の5ペアのみ。それ以外の通貨ペア（USD/CAD、USD/CHF、NZD/USD、EUR/JPY等）を分析対象にしない。
3. 暗号通貨に関する内容（BTC、ETH、ビットコイン、暗号資産、DeFi、Uniswap等）は一切含めない。原文に登場しても無視する。
4. X投稿にURL（Intent URL含む）を一切含めない。
5. 現値・数値は原文に記載された値をそのまま転記する（桁・小数点も原文どおり。四捨五入や概算をしない）。
6. 出力は有効なJSONオブジェクトのみ。説明文・コードフェンス・コメントは出力しない。

# 出力JSONスキーマ
{
  "date_jst": "{DATE_ISO}",
  "themes": [
    {
      "icon": "oil | market | bank | globe | percent | default のいずれか",
      "title": "テーマ見出し（16文字以内）",
      "desc": "説明2行。改行\\nで区切る。各行28文字以内",
      "impact": "影響の要約（12文字以内。「影響：」は付けない）",
      "impact_dir": "up | down | flat"
    }
    // ちょうど3件。本日の最重要テーマ順
  ],
  "pairs_image": [
    {
      "pair": "USD/JPY 等（5ペアから本日重要な3つを選定）",
      "dir": "up | down | flat（本日の方向感）",
      "label": "方向感の一言（8文字以内）",
      "reason": "根拠（42文字以内）",
      "badge": "半角英大文字の短いバッジ。1〜2語（例: CPI FOCUS / RBA HAWKISH / SAFE HAVEN）"
    }
    // ちょうど3件
  ],
  "report_md": "レポート本文（Markdown・下記構成）",
  "post1": "X投稿1（下記仕様）",
  "post2": "X投稿2（下記仕様）"
}

# report_md の構成
1行目: 「# {DATE_JA}（{WEEKDAY_JA}） Westpac IQ Morning Report」
「## 1. ファンダメンタルズ・マクロ経済分析」— 主要テーマ3件を軸に、原文の市場データ（株式・金利・コモディティ・為替）を織り込んで400〜700字で文章化。
「## 2. テクニカル分析と本日の展望」— 対象5ペア（USD/JPY・AUD/USD・XAU/USD・EUR/USD・GBP/USD）それぞれについて、現値（原文値）・方向感・注目材料を箇条書きで。
「## 3. 本日の重要イベント」— 原文記載の当日イベントをMarkdown表（| 時刻(JST) | 国 | イベント | 予想 | 前回 |）で。時刻は原文がシドニー/GMT表記の場合JSTへ換算し、換算元が不明なら時刻を「未確認」とする。予想・前回が原文にない場合は「-」。
末尾に「出典: Westpac IQ Morning Report {DATE_SLASH}」の1行。

# post1（主要トピック要約）の仕様
- 1行目「【{DATE_MD}({WEEKDAY_JA}) 朝の為替市況】」
- 主要テーマ3件を「・」の箇条書きで各1行（簡潔に）
- 最終行: 「#FX #為替 #市況 #ドル円」
- URLなし

# post2（通貨別分析）の仕様
- 1行目「【通貨別分析 {DATE_MD}】」
- 5ペアすべてを次の形式で記載（この並び順: #USDJPY → #AUDUSD → #XAUUSD → #EURUSD → #GBPUSD）:
  「#USDJPY 現値 矢印(↑/↓/→) 方向感の一言」
  「根拠：〜（1行・簡潔に）」
  ペア間は空行1つ
- その後に「出典: Westpac IQ Morning Report {DATE_SLASH}」
- 最終行: 「#FX #為替 #ドル円 #ゴールド #GOLD #投資 #資産運用 #市況」（当日の主要材料に応じ #米CPI #米雇用統計 等を適宜追加してよい）
- URLなし

# Westpac IQ Morning Report 原文テキスト（{DATE_ISO}）
---
{PDF_TEXT}
---

有効なJSONオブジェクトのみを出力してください。
