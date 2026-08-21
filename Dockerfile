FROM minizinc/minizinc:latest-alpine

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /code

RUN apk --no-cache add \
        gcc \
        python3-dev

COPY uv.lock pyproject.toml /code/

RUN uv sync --locked --no-dev

COPY minizinc_discord.py /code

CMD ["uv", "run", "--no-sync", "python", "minizinc_discord.py"]
