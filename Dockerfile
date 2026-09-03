FROM python:3.9-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    FLASK_APP=app.py \
    DATA_DIR=/app/data \
    PORT=10000 \
    TZ=Asia/Shanghai

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p downloads data/config data/media data/logs

VOLUME ["/app/data", "/app/downloads"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python3 -c "import os, requests; requests.get('http://localhost:' + os.environ.get('PORT', '10000') + '/login', timeout=5)" || exit 1

EXPOSE 10000

CMD ["python3", "run.py"]
