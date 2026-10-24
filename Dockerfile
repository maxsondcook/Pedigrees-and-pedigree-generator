FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
# Railway sets $PORT. Not "::": asyncio makes that IPv6-only, and Railway's
# healthcheck connects over IPv4. Private networking reaches IPv4 too.
CMD ["sh", "-c", "uvicorn crossr_api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
