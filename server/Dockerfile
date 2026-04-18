FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy SDK (shared types)
COPY sdk/ /sdk
RUN uv pip install --system /sdk

# Copy server project files
COPY server/pyproject.toml .
COPY server/src/ src/
COPY server/alembic/ alembic/
COPY server/alembic.ini .

# Install server dependencies
RUN uv pip install --system -e .

# Default command: run the server
CMD ["python", "-m", "deliberate_server.main"]
