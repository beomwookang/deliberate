FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml .
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .

# Install dependencies
RUN uv pip install --system -e ".[dev]"

# Default command: run the server
CMD ["python", "-m", "deliberate_server.main"]
