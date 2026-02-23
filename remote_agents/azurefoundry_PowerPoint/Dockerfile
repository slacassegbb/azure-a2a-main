FROM python:3.12-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates apt-transport-https lsb-release gnupg \
    && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock* ./
RUN uv pip install --system -e .
COPY . .

ENV A2A_PORT=9036
ENV A2A_HOST=0.0.0.0
EXPOSE ${A2A_PORT}

CMD ["sh", "-c", "uv run . --host ${A2A_HOST} --port ${A2A_PORT}"]
