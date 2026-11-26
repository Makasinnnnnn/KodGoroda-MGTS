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
CMD ["python", "app.py"]
