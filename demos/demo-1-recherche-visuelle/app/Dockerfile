FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HF_HOME=/models PIP_NO_CACHE_DIR=1

WORKDIR /srv
RUN pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY demo ./demo
EXPOSE 8000
CMD ["uvicorn", "demo.server:app", "--host", "0.0.0.0", "--port", "8000"]
