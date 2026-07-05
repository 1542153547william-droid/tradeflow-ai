FROM python:3.11-slim

WORKDIR /app

# Aliyun PyPI mirror — fast from mainland China. Override with a build-time
# --build-arg PIP_INDEX_URL=... if deploying elsewhere.
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

# Install deps first so the layer caches across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# One worker is plenty early on; the agent is I/O-bound on the model API.
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
