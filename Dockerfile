FROM python:3.11-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY *.py ./
COPY data/ ./data/
COPY web/ ./web/
RUN python ingest.py && useradd --create-home visitor && mkdir -p /state && chown visitor:visitor /state
USER visitor
EXPOSE 18943
CMD ["python", "serve.py", "--host", "0.0.0.0", "--db", "/state/sessions.sqlite"]
