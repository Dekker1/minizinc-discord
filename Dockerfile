# Build the virtual environment separately, so uv stays out of the final image
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build

WORKDIR /code
COPY uv.lock pyproject.toml ./
RUN uv sync --locked --no-dev

FROM python:3.13-slim-bookworm

# https://docs.minizinc.dev/en/latest/installation.html#adding-minizinc-to-your-own-image
COPY --from=ghcr.io/minizinc/minizinc:edge-dist /opt/minizinc /opt/minizinc
COPY --from=build /code/.venv /code/.venv
COPY minizinc_discord.py /code/

ENV PATH=/opt/minizinc/bin:/code/.venv/bin:$PATH \
    LD_LIBRARY_PATH=/opt/minizinc/lib

WORKDIR /code
CMD ["python", "minizinc_discord.py"]
