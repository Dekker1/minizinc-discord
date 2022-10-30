FROM minizinc/minizinc:latest-alpine

WORKDIR /code

RUN apk --no-cache add \
        gcc \
        python3-dev \
        poetry

COPY poetry.lock /code
COPY pyproject.toml /code

RUN poetry install

COPY minizinc_discord.py /code

CMD ["poetry", "run", "python", "minizinc_discord.py"]
