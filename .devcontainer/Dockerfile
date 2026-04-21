FROM python:3.12-slim

WORKDIR /app

# 1. 以 root 用户身份执行安装
USER root

# 2. 更新包列表并清理 apt 缓存
RUN apt-get update && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt
