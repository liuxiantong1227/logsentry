# 基础镜像
FROM python:3.13-slim

# 环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 【关键】先只拷贝依赖清单并安装 —— 利用 Docker 的分层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷贝项目代码
COPY . .

# 数据目录(容器内)
RUN mkdir -p data

EXPOSE 8000

# 容器启动:先确保有演示数据,再启动服务
CMD ["sh", "-c", "python scripts/seed_demo.py && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]