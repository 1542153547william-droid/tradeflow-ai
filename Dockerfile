FROM python:3.11-slim

WORKDIR /app

# Install deps first so the layer caches across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# One worker is plenty early on; the agent is I/O-bound on the model API.
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
