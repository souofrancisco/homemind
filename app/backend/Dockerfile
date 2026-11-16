FROM python:3.12.8-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/srv/src PATH=/srv/.venv/bin:$PATH
COPY pyproject.toml uv.lock ./
# Só dependências (cache); o código é montado/copiado depois e corre via PYTHONPATH.
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN useradd -m app && mkdir -p /srv/data && chown app /srv/data
USER app
EXPOSE 8000
CMD ["uvicorn", "homemind.main:app", "--host", "0.0.0.0", "--port", "8000"]
