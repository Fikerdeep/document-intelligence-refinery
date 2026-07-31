FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir -e .

COPY rubric/ rubric/
COPY scripts/ scripts/
COPY eval/ eval/

ENTRYPOINT ["python"]
CMD ["scripts/ingest.py", "--help"]
