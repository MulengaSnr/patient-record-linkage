# Airflow with the project in its own virtual environment. Tasks run the
# project's commands from that environment, so Airflow's pinned dependencies
# and Splink's cannot conflict. Images are pinned by digest.
FROM apache/airflow:3.3.2-python3.12@sha256:9df9c8be4096b9cc626bd7cb1f2b8c712eef66c59c615f8c7e6200871ca10bd1
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /bin/uv

USER root
ENV UV_PYTHON=3.12 UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
WORKDIR /opt/linkage
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY configs ./configs
COPY sql ./sql
RUN uv sync --locked --no-default-groups && chown -R airflow:0 /opt/linkage

USER airflow
WORKDIR /opt/airflow
