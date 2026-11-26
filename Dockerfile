FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MGTS_CONTAINER=1
COPY requirements.txt requirements-import.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py google_forms.py ./
COPY scripts ./scripts
COPY templates ./templates
COPY static ./static
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/health', timeout=2).close()"]
CMD ["python", "app.py"]
