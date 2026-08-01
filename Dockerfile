FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    INSIGHTFLOW_ROOT_DIR=/app \
    INSIGHTFLOW_DB_PATH=/app/data/warehouse/insightflow.db \
    INSIGHTFLOW_SERVER_ADDRESS=0.0.0.0 \
    INSIGHTFLOW_SERVER_PORT=8501

WORKDIR /app

RUN groupadd --system insightflow && useradd --system --gid insightflow --create-home insightflow
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY streamlit_app.py docker-entrypoint.sh ./
COPY .streamlit ./.streamlit
COPY contracts ./contracts
COPY scripts ./scripts
RUN pip install . && chmod +x /app/docker-entrypoint.sh

RUN mkdir -p /app/data /app/reports /app/powerbi /app/portfolio \
    && chown -R insightflow:insightflow /app
USER insightflow

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["insightflow", "run", "--", "--server.headless=true", "--browser.gatherUsageStats=false"]
