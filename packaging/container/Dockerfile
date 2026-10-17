FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY packaging/requirements-web.lock /app/requirements-web.lock
RUN pip install --no-cache-dir -r requirements-web.lock
COPY pyproject.toml README.md LICENSE /app/
COPY otam /app/otam
RUN pip install --no-cache-dir --no-deps --no-build-isolation . && \
    groupadd --gid 10001 otam && useradd --uid 10001 --gid otam --no-create-home otam && \
    mkdir /data && chown otam:otam /data
USER 10001:10001
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3)" || exit 1
ENTRYPOINT ["otam"]
CMD ["serve", "--config", "/etc/otam/node.json"]
