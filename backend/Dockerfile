FROM public.ecr.aws/docker/library/python:3.13.2-slim-bookworm

# Install system dependencies needed for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install lambda web adapter
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.7.0 /lambda-adapter /opt/extensions/lambda-adapter

WORKDIR /backend

COPY ./pyproject.toml ./poetry.lock ./

ENV POETRY_REQUESTS_TIMEOUT=10800

# Install pip and poetry
RUN python -m pip install --upgrade pip && \
    pip install poetry --no-cache-dir

# Configure poetry
RUN poetry config virtualenvs.create false

# Update lock file to include watchtower and sync with pyproject.toml
RUN poetry lock --no-update

# Install dependencies
RUN poetry install --no-interaction --no-ansi --only main

# Clear cache to reduce image size
RUN poetry cache clear --all pypi

COPY ./app ./app

ENV PORT=8000
EXPOSE ${PORT}
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]