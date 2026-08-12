# HANDOFF: Westpac Morning Report パイプライン（Claude Code向け引き継ぎ書）

あなた（Claude Code）への依頼: このフォルダ一式をGitHubリポジトリとして稼働させ、初回の動作検証まで完了させてください。**ユーザーはGitHub Issue初心者**です。作業は逐一わかりやすく報告してください。

## 背景（1分で把握）
- Manusで運用中の「Westpac IQ Morning Report → 日本語朝レポ＋X投稿」自動納品を、Manus停止（8/23〜25）を機にGitHub Actions＋Claude APIへ移行する
- 検収チャネルは **GitHub Issue単体**（毎朝自動起票 → ユーザーがスマホで確認 → 手動でX投稿 → Close）
- 方式A（手動投稿）で開始し、安定後に方式B（Issue承認→X API自動投稿）へ拡張する
- 同型のクリプト投稿パイプラインが別リポジトリで稼働中。**本件は暗号通貨の内容が全面禁止**のため、リポジトリは必ず分離する

## セットアップ手順
1. `gh auth status` を確認（未ログインなら `gh auth login`）
2. プライベートリポジトリ作成と初回push:
   ```bash
   cd <このフォルダ>
   git init && git add -A && git commit -m "WMR pipeline phase 1"
   gh repo create westpac-morning-report --private --source=. --push
   ```
3. Secret登録: `gh secret set ANTHROPIC_API_KEY`（値はユーザーに確認。クリプト側と共用可）
4. サンプル実行（外部アクセス・API消費なし）:
   ```bash
   gh workflow run daily.yml -f sample=true
   gh run watch   # 完了後
   gh issue list  # 「【検収】…（テスト実行）」が立っていること
   ```
   Issueを開き、レポート画像・チャート枠・投稿文・G1〜G8の表が正しく表示されるか確認
5. 本番実行（当日レポート発行後の時間帯に）: `gh workflow run daily.yml`
   - 成功: 【検収】Issueに実データが載る
   - 失敗: 下記「初回で想定されるつまずき」を参照して修正
6. ユーザーへ案内: GitHubアプリでリポジトリを **Watch → All Activity** に設定してもらう

## 初回で想定されるつまずきと対処
- **候補ゼロ（exit 4）/ 当日記事を特定できない（exit 3が連発）**
  `sources/<date>/debug_topic.html` を読み、実際のDOMに合わせて `scripts/fetch_westpac.py` の候補抽出条件（現在: hrefかリンクテキストに "morning" を含む記事URL）を調整する。一覧はJS描画のため待機9秒。足りなければ延長。
- **PDFリンク不検出**: `debug_article.html` を確認。記事内のダウンロードボタンのhref形式に合わせて抽出を追加する（現在: `a[href*=".pdf"]` ＋ HTML全文の `.pdf` 正規表現）
- **PDFでない応答（認証壁）**: `debug_pdf_response.bin` を確認。Actionsの海外IPがブロックされる場合は、待機延長・UA調整で解決しないか試し、だめならユーザーに報告して代替（セルフホストランナー等）を協議
- **G8数値照合のFAIL多発**: 生成が数値を丸めている。`prompts/generate_prompt.md` の「原文どおり転記」の指示を強化する（verifyの緩和は最後の手段）
- **チャートがほぼ無地**: `capture_charts.py` の `--wait` を延長（TradingViewウィジェット8枚の描画待ち）

## 品質基準（変えないこと）
- 対象5ペア限定・暗号通貨語ゼロ・投稿にURLなし・出典表記・数値はPDF原文一致（G1〜G8）
- レポート画像はAI画像生成ではなく `render_image.py` の決定論的描画（レイアウト勝手に変更しない）
- 未発行・エラーの通知Issueは最終試行（8:40）と手動実行のみ（通知過多の防止）

## 運用開始後
- **5営業日はManusと並走**（シャドー運用）し、内容を突き合わせてからManusの定期タスクを停止するようユーザーに案内
- 60日より古い `outputs/` `sources/` は日次で自動削除される（`run_daily.py`）

## 方式B（フェーズ2）実装メモ — 着手はユーザー承認後
- トリガー: 検収Issueへの「承認」コメント（`issue_comment` イベント、投稿者==リポジトリオーナー限定）
- X API: 2026年2月以降の新規はPay-Per-Use（投稿$0.01/件・最低$5前払い、本件月44投稿≈$0.44）。導入時に開発者ポータルで最新料金と**画像アップロードの課金有無**を必ず確認
- 投稿1→投稿2（画像添付）の順に投稿し、結果をIssueにコメント→自動Close
- Secretsに X_API_KEY 等を追加。誤爆防止に「承認」完全一致＋24時間以内のIssueのみ反応
