# CloudBase 云托管 Dockerfile
# 应急决策教学系统

FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple/

# 复制项目文件
COPY . .

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV SCENARIOS_DIR=/app/scenarios
ENV PORT=80

# 暴露端口
EXPOSE 80

# 启动命令（CloudBase 云托管通过 PORT 环境变量指定端口）
CMD gunicorn -w 4 -b 0.0.0.0:${PORT} --timeout 120 wsgi:app
