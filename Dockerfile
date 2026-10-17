FROM python:3.14-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt:/opt/agent

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

# Keep the full package tree image-owned and read-only.  The legacy core
# citations used by identity explanations resolve to the moved sources.
# Docker remains the security boundary because SELF runs as root inside it.
RUN mkdir -p /opt/agent/core \
    && ln -s ../runtime/loop.py /opt/agent/core/loop.py \
    && ln -s ../tools/base_tools.py /opt/agent/core/base_tools.py \
    && ln -s ../infra/hardening.py /opt/agent/core/hardening.py \
    && ln -s ../infra/event_log.py /opt/agent/core/event_log.py \
    && ln -s ../tools/tool_registry.py /opt/agent/core/tool_registry.py \
    && ln -s ../ui/wake.py /opt/agent/core/wake.py \
    && chown -R root:root /opt/agent \
    && find /opt/agent -type d -exec chmod 0555 {} + \
    && find /opt/agent -type f -exec chmod 0444 {} +

# Make the execution identity explicit: the container is intentionally root
# inside its own namespace, while Docker remains the security boundary.
USER root

ENTRYPOINT ["python", "-m", "agent.wake"]
