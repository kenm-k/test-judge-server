# APIサーバー用のコンテナ
FROM python:3.11-slim

WORKDIR /app

# 必要なライブラリをインストール
# fastapi: REST APIを作るためのフレームワーク
# uvicorn: サーバーを動かすエンジン
# docker: PythonからDockerを操作するためのライブラリ
RUN pip install --no-cache-dir fastapi uvicorn docker pydantic

COPY main.py .

# サーバー起動 (0.0.0.0:8000 で待ち受け)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
