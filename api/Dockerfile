# build context = 專案根目錄（為了 COPY common/），dockerfile 由 compose 指定 api/Dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ ./common/
COPY api/app.py api/auth.py api/db_auth.py api/email_sender.py ./

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
