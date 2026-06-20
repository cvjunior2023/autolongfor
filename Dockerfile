# ============================================================
# 龙湖天街自动化签到 - Docker 镜像
# ============================================================

FROM python:3.12-slim

ARG MAINTAINER="autolongfor"
ARG BRANCH="unknown"
ARG BUILD_SHA="unknown"
ARG BUILD_TAG="unknown"

LABEL maintainer="${MAINTAINER}"
LABEL branch="${BRANCH}"
LABEL org.opencontainers.image.source="https://github.com/cvjunior/autolongfor"
LABEL org.opencontainers.image.revision="${BUILD_SHA}"
LABEL org.opencontainers.image.version="${BUILD_TAG}"

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY main.py .
COPY lhtj_data.json .

# 创建数据持久化目录（用于 assist_status.json）
RUN mkdir -p /data && ln -sf /data/assist_status.json assist_status.json

# 默认运行所有任务
CMD ["python", "main.py"]
