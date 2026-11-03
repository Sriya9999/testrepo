FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home app && mkdir -p /data/storage && chown -R app /app /data
USER app
ENV STORAGE_DIR=/data/storage AUTO_CREATE_TABLES=false
EXPOSE 8000
# The API container applies migrations before serving; the worker runs `python -m app.worker`.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
