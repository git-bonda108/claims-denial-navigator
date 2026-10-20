FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/data/synthetic
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY denialnav ./denialnav
COPY web ./web
RUN useradd -m app && mkdir -p /app/data && chown -R app /app
USER app
EXPOSE 8000
# The synthetic dataset is generated on first start (dated "today"), so deadlines stay current.
CMD ["uvicorn", "denialnav.api:app", "--host", "0.0.0.0", "--port", "8000"]
