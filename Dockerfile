FROM python:3.11-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY *.py ./
COPY data/ ./data/
COPY web/ ./web/
COPY skills/ ./skills/
RUN python ingest.py && useradd --create-home visitor && mkdir -p /state && chown visitor:visitor /state
USER visitor
EXPOSE 18943
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:18943/health',timeout=4)" || exit 1
CMD ["python", "serve.py", "--host", "0.0.0.0", "--db", "/state/sessions.sqlite"]
