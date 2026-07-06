# Query-system service image. Build context = query-system/ (needs backend + frontend).
FROM python:3.11-slim

WORKDIR /app

# Aliyun PyPI mirror — fast from mainland China.
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

# Deps first for layer caching. (Playwright's browser binaries are NOT installed
# here — mock/api modes don't need them. For real scraping add `playwright install`.)
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY frontend ./frontend

WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
