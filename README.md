# Trailer App

ライト・トレーラ連結仕様検討、車軸強度、車枠強度、安定角、最小回転半径などの計算ツール（wxPython GUI）。

## セットアップ (Windows)

```powershell
# リポ取得
Set-Location "C:\Users\takas\Documents\GitHub"
git clone https://github.com/kaitakappe/Trailer-app.git
Set-Location Trailer-app

# 仮想環境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 依存関係
pip install -U pip
pip install -r requirements.txt
```

日本語フォントをPDFに埋め込むため `ipaexg.ttf` をリポ直下に配置済みです。ReportLab で自動検出されます。

## 実行

VS Code のデバッグ構成「Python: Run main.py」から実行、または下記を実行します。

```powershell
& ".\.venv\Scripts\python.exe" ".\main.py"
```

## PDF 出力

- ReportLab を使用しています。出力後は既定アプリで自動オープンします（Windows）。
- 連結仕様検討書は、車両情報（車名・型式・登録番号・シリアル番号・車体の形状）と諸元表、各判定の式展開を1ページに出力します。

## 開発メモ

- VS Code ワークスペース設定は `.vscode/` と `Trailer-app.code-workspace` に含まれます。
- 依存関係: `wxPython`, `reportlab`
- Python バージョン: 3.10 以降を推奨

## ライセンス

プロジェクトルートの LICENSE がないため、私用目的での利用を前提としています。必要ならライセンスを追加してください。
