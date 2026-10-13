FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends chromium fonts-noto-core ca-certificates && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/chromium /usr/local/bin/chromium-browser \
    && useradd -m -u 10001 appuser
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py /app/
COPY pvpoke_meta_opponents.csv /app/pvpoke_meta_opponents.csv
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh && chown -R appuser:appuser /app
USER appuser
CMD ["/app/start.sh"]
