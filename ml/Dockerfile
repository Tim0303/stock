FROM python:3.12-slim

WORKDIR /app

# 系統相依（psycopg2-binary 已含 wheel，無需編譯，但保留 ca-certs）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 模型輸出目錄（train 會寫入；.gitignore 已忽略 *.pkl）
RUN mkdir -p /app/models

ENTRYPOINT ["python", "main.py"]
