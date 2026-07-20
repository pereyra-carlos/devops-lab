FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY app/requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd -g 1000 app && useradd -u 1000 -g app -m app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app/main.py .

ARG GIT_SHA=dev
ARG BUILD_TIME=unknown
ARG APP_VERSION=0.5.1
ENV GIT_SHA=$GIT_SHA \
    BUILD_TIME=$BUILD_TIME \
    APP_VERSION=$APP_VERSION

USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health').status==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
