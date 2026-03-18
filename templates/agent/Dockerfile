FROM python:3.11-slim

ARG PIP_EXTRA_INDEX_URL

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

EXPOSE 8000

RUN useradd --create-home appuser
USER appuser

CMD ["uvicorn", "{{package_name}}.main:app", "--host", "0.0.0.0", "--port", "8000"]
