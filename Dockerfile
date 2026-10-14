FROM python:3.12-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt:/opt/agent/core:/opt/agent

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
COPY agent/requirements.txt /opt/agent/requirements.txt
RUN python -m pip install --no-cache-dir -r /opt/agent/requirements.txt

COPY agent/ /opt/agent/

# The complete Python harness is moved into a distinct image-owned core and
# made read-only for ordinary writes.  Compatibility symlinks retain the
# `agent.*` module paths while all runtime code resolves into `/opt/agent/core`.
# Docker—not Unix mode bits—is still the real security boundary because SELF
# intentionally runs as root inside it.
RUN mkdir -p /opt/agent/core \
    && for source in /opt/agent/*.py; do \
         file="$(basename "$source")"; \
         if [ "$file" = "__init__.py" ]; then continue; fi; \
         mv "$source" "/opt/agent/core/$file"; \
         ln -s "core/$file" "$source"; \
       done \
    && mv /opt/agent/providers /opt/agent/core/providers \
    && ln -s core/providers /opt/agent/providers \
    && chown -R root:root /opt/agent/core \
    && find /opt/agent/core -type d -exec chmod 0555 {} + \
    && find /opt/agent/core -type f -exec chmod 0444 {} +

# Make the execution identity explicit: the container is intentionally root
# inside its own namespace, while Docker remains the security boundary.
USER root

ENTRYPOINT ["python", "-m", "agent.wake"]
