FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    WEB_CONCURRENCY=2
WORKDIR /code
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY . .
# Run as an unprivileged user (uid 1000 matches the usual host user, so the
# bind-mounted code and media folder in docker-compose stay writable)
RUN useradd --uid 1000 --create-home app && mkdir -p media && chown app:app media
USER app
EXPOSE 8000
# uvicorn reads WEB_CONCURRENCY (workers) and FORWARDED_ALLOW_IPS (proxy) from the env
# live pages hold connections open; don't let them block a restart for more than 5 s
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", \
     "--timeout-graceful-shutdown", "5"]
