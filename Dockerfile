# Portable deployment image for one Oryveta API or worker process.
# This image is not a production multi-tenant security boundary.
FROM python:3.12-slim
WORKDIR /service
COPY pyproject.toml README.md LICENSE ./
COPY apps ./apps
COPY engine ./engine
RUN pip install --no-cache-dir -e . && mkdir -p /data && chown -R 65532:65532 /data
ENV ORYVETA_DATABASE_PATH=/data/oryveta.db \
    ORYVETA_WORKSPACE_ROOT=/data/workspaces \
    PYTHONUNBUFFERED=1
USER 65532:65532
EXPOSE 8000
CMD ["uvicorn", "oryveta_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
