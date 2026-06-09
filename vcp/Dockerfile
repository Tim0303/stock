FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 用法：
#   docker compose run --rm vcp scan       # 近期掃描，突破日寫 analyses
#   docker compose run --rm vcp bootstrap  # 歷史所有突破日寫 analyses(meta backtest)
#   docker compose run --rm vcp backtest   # VCP 進出場回測，印 PF/勝率/平均持有
ENTRYPOINT ["python", "main.py"]
