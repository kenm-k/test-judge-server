# 提出されたコードをコンパイル＆実行するための「使い捨て」コンテナ
FROM ubuntu:22.04

# C++コンパイラをインストール
RUN apt-get update && apt-get install -y \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
