# Westpac Morning Report 自動生成パイプライン（フェーズ1）

毎朝8時台に **Westpac IQ Morning Report のPDFを取得 → 日本語レポート・X投稿2本・レポート画像・チャート画像を自動生成 → GitHub Issueで検収依頼** まで無人で行う仕組みです。あなたはスマホの通知を確認し、問題なければコピーしてXへ投稿するだけです（方式A）。

```
8:00 JST（未発行なら8:20 / 8:40に再試行）
  │ GitHub Actions が自動起動
  ├ 1. westpaciq.com.au から当日PDFを取得・テキスト抽出
  ├ 2. 6forex.netlify.app のチャートをスクリーンショット
  ├ 3. Claude APIで本文・投稿1・投稿2・画像用データを生成
  ├ 4. レポート画像（16:9・紺×金）をプログラムで描画
  ├ 5. 機械検証ゲート（日付・数値照合・禁止語・5ペア限定 など8項目）
  └ 6. 検収Issueを自動起票 → スマホに通知
        ↓
   あなた: 内容確認 → コピー → Xアプリで投稿 → IssueをClose
```

## 必要なもの
- GitHubアカウント（無料。スマホにGitHubアプリを入れておく）
- Anthropic APIキー（クリプト投稿パイプラインと同じキーを共用してOK）
- Xアカウントは **Xプレミアム（長文投稿可）** で運用（投稿2は5ペア分を並べるため280字を超えます。検証結果のI1/I2は文字数を参考表示するのみで、280字超の警告は出しません）

## セットアップ（推奨: Claude Codeに依頼）
`HANDOFF_claude_code.md` をClaude Codeに渡し、「この手順書どおりにセットアップして」と依頼するのが最も簡単です。以下は手動で行う場合の手順です。

1. **プライベートリポジトリを作成**
   github.com → 右上「+」→ New repository → 名前 `westpac-morning-report` → **Private** → Create
2. **このフォルダの中身をすべてアップロード**
   リポジトリ画面 → Add file → Upload files → このzipを展開した中身をドラッグ（`.github` フォルダごと）→ Commit
3. **APIキーを登録**
   リポジトリの Settings → Secrets and variables → Actions → New repository secret
   Name: `ANTHROPIC_API_KEY` ／ Secret: あなたのAPIキー
4. **Actionsを有効化**
   Actionsタブを開き、有効化を求められたら承認
5. **サンプルテスト（Westpacにもアクセスせず、API料金もかからない）**
   Actionsタブ → Westpac Morning Report → Run workflow → `sample` に **チェックを入れて** 実行
   → 数分後、Issuesタブに「【検収】…（テスト実行）」が立てば成功
6. **本番テスト**
   同じく Run workflow を `sample` **チェックなし** で実行（平日の朝〜昼推奨。当日レポート発行後）
7. **スマホの通知設定**
   GitHubアプリでこのリポジトリを開く → 右上「…」→ **Watch → All Activity**
   （アプリの Settings → Notifications でプッシュ通知をON）

## 毎朝の運用（方式A）
1. 8時台にスマホへ「【検収】YYYY/MM/DD Westpac Morning Report」の通知
2. Issueを開き、画像2枚と投稿文・検証結果（G1〜G8）を確認
3. 投稿1・投稿2をコピー → Xアプリで投稿（投稿2にレポート画像を添付）
4. Issue下部のチェックボックスを付けて **Close**

- タイトルが **【FAIL・投稿禁止】** の日は投稿せず、Issueのコメントに気づいた点を書いてください
- **【未発行】** の日は豪州祝日などの可能性。休刊ならそのままCloseでOK
- ハッシュタグ本数はA/B検証中（A案=2個、B案=3個、週次で切替）。現在はA案（投稿1=「#ドル円」＋当日の材料タグ1個、投稿2=「#ドル円 #為替」。投稿2本文中のペアタグは対象外）

## 費用の目安
- GitHub Actions: プライベートリポジトリ無料枠 月2,000分に対し、本運用は月150〜200分程度
- Claude API: 1日1回の生成（入力1〜2万字・出力数千字）で、月に数十円〜数百円規模
- 画像生成は**プログラム描画のためAPI費用ゼロ**（Manusのgenerate_imageの置き換え）

## 重要: Manus側の停止
本番運用を開始したら、**Manusの定期タスクを必ず停止**してください（二重生成・二重投稿の防止）。Manus停止期間（8/23〜25）前に5営業日ほど並走させ、内容を突き合わせるのが安全です。

## トラブル時
- 取得に失敗した日は `sources/<日付>/debug_*.html` が保存されます。エラーIssueのログと合わせてClaude Codeに「調査して」と渡してください
- 生成内容の品質を変えたいときは `prompts/generate_prompt.md` を編集します（コードの変更は不要）
- 画像のデザイン調整は `scripts/render_image.py` の冒頭の色・座標定数で行えます

## フェーズ2（方式B）の予定
検収Issueに「承認」とコメントする（またはボタンを押す）と、X API（Pay-Per-Use・投稿$0.01/件）で自動投稿する拡張を、方式Aが安定運用できてから実装します。
