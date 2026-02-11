FROM public.ecr.aws/lambda/python:3.13

# Copy only pyproject.toml, poetry.lock will be generated
COPY ./pyproject.toml ./

ENV POETRY_REQUESTS_TIMEOUT=10800
RUN python -m pip install --upgrade pip && \
    pip install poetry --no-cache-dir && \
    poetry config virtualenvs.create false && \
    poetry lock && \
    poetry install --no-interaction --no-ansi --only main && \
    poetry cache clear --all pypi

COPY ./app ./app
COPY ./embedding_statemachine ./embedding_statemachine

CMD ["app.websocket.handler"]