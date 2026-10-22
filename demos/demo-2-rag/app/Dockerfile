FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY demo ./demo
EXPOSE 8000
CMD ["uvicorn", "demo.server:app", "--host", "0.0.0.0", "--port", "8000"]
