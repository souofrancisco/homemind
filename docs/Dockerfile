FROM python:3.12-slim

WORKDIR /docs

COPY docs/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY docs/serve.sh /usr/local/bin/serve-docs
RUN chmod +x /usr/local/bin/serve-docs

EXPOSE 8000

# Só pré-visualização local. O GitHub Pages constrói o site estático no Actions.
CMD ["serve-docs"]
