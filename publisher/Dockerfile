# Publisher: Chromium (from the official Playwright image) + ffmpeg + CJK fonts.
# Build context is the project root: docker compose builds it as the "publisher" service.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg xvfb xauth fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -u 10001 -m studio \
 && mkdir /pubdata && chown studio:studio /pubdata
WORKDIR /app
COPY requirements.txt publisher/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=studio:studio . .
# Same uid as the web app, so it can read the app's volume (mounted read-only).
USER studio
ENV DATA_DIR=/data PUBLISHER_DIR=/pubdata APP_ROOT=/app PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8200
# A real (virtual-display) browser window: headless Chrome is easier for platforms to flag.
CMD ["xvfb-run", "-a", "-s", "-screen 0 1366x900x24", "python", "-m", "publisher.worker"]
