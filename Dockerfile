FROM python:3.12-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        curl \
        jq \
        nano \
        vim \
        procps \
        net-tools \
        iputils-ping \
        dnsutils \
        sqlite3 \
        python3-venv \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /home/entity

# The agent harness is image content. Runtime state belongs in ./workspace,
# which is the only host path mounted by docker-compose.yml.
COPY agent/ /opt/agent/

# Make the execution identity explicit: the container is intentionally root
# inside its own namespace, while Docker remains the security boundary.
USER root

CMD ["/bin/bash"]
