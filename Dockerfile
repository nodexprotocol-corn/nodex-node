FROM python:3.11-slim

ARG TARGETARCH
ENV SINGBOX_VERSION=1.12.12

RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 curl ca-certificates tar gzip procps \
    && rm -rf /var/lib/apt/lists/*

RUN ARCH=$([ "$TARGETARCH" = "arm64" ] && echo "arm64" || echo "amd64") \
    && curl -fsSL "https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VERSION}/sing-box-${SINGBOX_VERSION}-linux-${ARCH}.tar.gz" -o /tmp/sb.tar.gz \
    && tar -xzf /tmp/sb.tar.gz -C /tmp \
    && mv /tmp/sing-box-${SINGBOX_VERSION}-linux-${ARCH}/sing-box /usr/local/bin/sing-box \
    && chmod +x /usr/local/bin/sing-box \
    && rm -rf /tmp/sb.tar.gz /tmp/sing-box-*

RUN pip install --no-cache-dir httpx>=0.24.0

WORKDIR /app
COPY agent.py /app/agent.py

CMD ["python3", "-u", "/app/agent.py"]
