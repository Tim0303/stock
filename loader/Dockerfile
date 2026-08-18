# build context = 專案根目錄（為了 COPY common/），dockerfile 由 compose 指定 loader/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY loader/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common/ ./common/
COPY loader/main.py .
ENTRYPOINT ["python", "main.py"]
