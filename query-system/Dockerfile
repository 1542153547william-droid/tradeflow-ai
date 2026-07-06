# Query-system service image. Build context = query-system/ (needs backend + frontend).
FROM python:3.11-slim

WORKDIR /app

# Aliyun PyPI mirror + npmmirror for Playwright browser binaries — fast from China.
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright

# Aliyun apt mirror so `playwright install --with-deps` pulls system libs fast.
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
      /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Chromium + system deps for scraper mode (adds a few hundred MB to the image).
RUN playwright install --with-deps chromium

COPY backend ./backend
COPY frontend ./frontend

WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
