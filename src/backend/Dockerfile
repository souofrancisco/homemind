FROM python:3.12.8-slim
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml ./
# Instala só dependências (cache): ficheiros de app copiados depois.
RUN python - <<'PY' > /tmp/req.txt
import tomllib
print("\n".join(tomllib.load(open("pyproject.toml","rb"))["project"]["dependencies"]))
PY
RUN pip install --no-cache-dir -r /tmp/req.txt
COPY app ./app
RUN useradd -m app && mkdir -p /srv/data && chown app /srv/data
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
