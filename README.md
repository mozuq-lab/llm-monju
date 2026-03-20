# 文殊 Monju

**三人寄れば文殊の知恵** -- 複数の LLM にお題を議論させ、ファシリテーター AI が結論を導き出す Web アプリケーション。

## 概要

一つのお題に対して Claude・ChatGPT・Gemini・Grok が複数ラウンドの議論を行い、独立したファシリテーター AI が論点を整理して最終結論を出力します。

### 議論の流れ

```
1. ファシリテーターが議論を開始し、お題の背景・論点を提示
2. 各ラウンド:
   - 全モデルが並列に回答
   - ファシリテーターが要約し、次の論点を提示
3. 最終ラウンド後、ファシリテーターが結論を構造化して出力
   (各主張の整理 → 合意点 → 相違点 → 総合結論)
```

## 対応モデル

| モデル | プロバイダ | 環境変数 | デフォルトモデル |
|--------|-----------|----------|-----------------|
| Claude | Anthropic | `ANTHROPIC_API_KEY` | claude-sonnet-4-6 |
| ChatGPT | OpenAI | `OPENAI_API_KEY` | gpt-4o |
| Gemini | Google | `GOOGLE_API_KEY` | gemini-2.0-flash |
| Grok | xAI | `XAI_API_KEY` | grok-2 |

API キーが設定されているモデルのみが自動的に参加します。**議論には最低 2 つのモデルが必要です。**

## セットアップ

### 1. 仮想環境の作成と依存パッケージのインストール

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. API キーの設定

```bash
cp .env.example .env
```

`.env` を編集し、利用するサービスの API キーを設定してください。

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AI...
XAI_API_KEY=xai-...       # 任意
```

### 3. サーバー起動

```bash
source .venv/bin/activate   # 未アクティベートの場合
python app.py
```

ブラウザで http://localhost:8000 を開くと議論画面が表示されます。

## 使い方

1. **お題を入力** -- 議論させたいテーマを入力
2. **ラウンド数を選択** -- 1〜5 ラウンド（デフォルト: 3）
3. **参加モデルを選択** -- チェックボックスで参加させるモデルを選択
4. **ファシリテーターを選択** -- 議論を取りまとめるモデルを指定
5. **「議論を開始」をクリック** -- リアルタイムで議論が表示される

## プロジェクト構成

```
llm-monju/
├── app.py              # FastAPI サーバー / API エンドポイント
├── debate.py           # 議論オーケストレーション
├── llm_clients.py      # 各 LLM の API クライアント
├── static/
│   └── index.html      # Web UI (HTML / CSS / JS)
├── requirements.txt
├── .env.example
└── .env                # API キー設定 (git 管理外)
```

## 技術スタック

- **バックエンド**: Python / FastAPI
- **フロントエンド**: HTML / CSS / JavaScript (フレームワーク不使用)
- **リアルタイム配信**: Server-Sent Events (SSE)
- **LLM SDK**: anthropic, openai, google-genai

## API

### `GET /api/models`

利用可能なモデル一覧を返します。

### `POST /api/debate`

議論を開始し、SSE ストリームで進行状況を返します。

```json
{
  "topic": "議論のお題",
  "num_rounds": 3,
  "models": ["claude", "chatgpt", "gemini"],
  "facilitator_model": "claude"
}
```

## ライセンス

MIT
