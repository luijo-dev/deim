FROM python:3.13-slim

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency manifests first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY app/ ./app/
COPY services/ ./services/
COPY main.py ./

# Cloud Run provides the PORT environment variable; default to 8080
ENV PORT=8080
EXPOSE 8080

# Run Streamlit bound to 0.0.0.0 and the Cloud Run port
CMD uv run streamlit run main.py --server.port="${PORT}" --server.address=0.0.0.0 --server.headless=true
