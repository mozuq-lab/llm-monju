# 文殊 Monju

**三人寄れば文殊の知恵** -- 複数の LLM にお題を議論させ、ファシリテーター AI が結論を導き出す Web アプリケーション。

## 概要

一つのお題に対して複数の LLM が複数ラウンドの議論を行い、独立したファシリテーター AI が論点を整理して最終結論を出力します。すべてのモデル呼び出しは [OpenRouter](https://openrouter.ai/) 経由で行うため、API キー 1 つであらゆるモデルを利用できます。

### 議論の流れ

```
1. ファシリテーターが議論を開始し、お題の背景・論点を提示
2. 各ラウンド:
   - 全モデルが並列に回答
   - ファシリテーターが要約し、次の論点を提示
3. 最終ラウンド後、ファシリテーターが結論を構造化して出力
   (各主張の整理 → 合意点 → 相違点 → 総合結論)
```

## デフォルトモデル

UI から表示名・モデル ID を自由に編集・追加・削除できます。

| 表示名 | デフォルトモデル ID |
|--------|-------------------|
| Claude | `anthropic/claude-sonnet-4-6` |
| ChatGPT | `openai/gpt-4o` |
| Gemini | `google/gemini-2.0-flash-001` |
| Grok | `x-ai/grok-2` |

モデル ID は [OpenRouter Models](https://openrouter.ai/models) から選べます。**議論には最低 2 つのモデルが必要です。**

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

`.env` を編集し、OpenRouter の API キーを設定してください。

```env
OPENROUTER_API_KEY=sk-or-...
```

API キーは [OpenRouter Keys](https://openrouter.ai/keys) から取得できます。

### 3. サーバー起動

```bash
source .venv/bin/activate   # 未アクティベートの場合
python app.py
```

ブラウザで `http://localhost:8000` を開くと議論画面が表示されます。

## 使い方

1. **お題を入力** -- 議論させたいテーマを入力
2. **ラウンド数を選択** -- 1〜5 ラウンド（デフォルト: 3）
3. **参加モデルを編集** -- 表示名とモデル ID を設定し、チェックで有効化
4. **ファシリテーターを設定** -- 結論を出すモデルの ID を指定
5. **「議論を開始」をクリック** -- リアルタイムで議論が表示される

## プロジェクト構成

```
llm-monju/
├── app.py              # FastAPI サーバー / API エンドポイント
├── debate.py           # 議論オーケストレーション
├── llm_clients.py      # OpenRouter API クライアント
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
- **LLM Gateway**: OpenRouter (OpenAI 互換 API)

## API

### `GET /api/defaults`

デフォルトのモデル一覧を返します。

### `POST /api/debate`

議論を開始し、SSE ストリームで進行状況を返します。

```json
{
  "topic": "議論のお題",
  "num_rounds": 3,
  "debaters": [
    {"model": "anthropic/claude-sonnet-4-6", "name": "Claude"},
    {"model": "openai/gpt-4o", "name": "ChatGPT"},
    {"model": "google/gemini-2.0-flash-001", "name": "Gemini"}
  ],
  "facilitator": {
    "model": "anthropic/claude-sonnet-4-6",
    "name": "Facilitator"
  }
}
```

## ライセンス

MIT
