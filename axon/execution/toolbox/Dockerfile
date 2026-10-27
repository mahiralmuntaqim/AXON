# AXON attacker toolbox (Option A).
#
# A single image with the allowlisted, documented pentest tools preinstalled. The AXON agent
# does NOT run tools on the host; it `docker exec`s each allowlisted command inside a container
# built from this image, joined to the challenge's Docker network. That way the tools actually
# exist and the target is reachable by its compose service name.
#
# This image installs documented tools only — it generates no exploit payloads.
#
# Build:  docker build -t axon-attacker-toolbox:latest axon/execution/toolbox
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Core tools, all in Debian bookworm main — the build fails if any of these is missing.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget git jq unzip \
      nmap netcat-openbsd dirb hydra sqlmap \
      python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Optional extras not always in main (nikto/whatweb). Best-effort: a missing one is skipped,
# not fatal — the Go/Rust web tools below cover the same ground.
RUN apt-get update && for pkg in nikto whatweb; do \
      apt-get install -y --no-install-recommends "$pkg" || echo "skip: $pkg unavailable"; \
    done; rm -rf /var/lib/apt/lists/*

# Go/Rust release binaries that Debian does not package: ffuf, gobuster, feroxbuster.
# Versions are pinned; bump these ARGs if a download 404s at build time.
ARG FFUF_VERSION=2.1.0
ARG GOBUSTER_VERSION=3.6.0
ARG FEROX_VERSION=2.10.4
RUN set -eux; cd /tmp; \
    curl -fsSL -o ffuf.tgz "https://github.com/ffuf/ffuf/releases/download/v${FFUF_VERSION}/ffuf_${FFUF_VERSION}_linux_amd64.tar.gz"; \
    tar -xzf ffuf.tgz ffuf && mv ffuf /usr/local/bin/ffuf; \
    curl -fsSL -o gobuster.tgz "https://github.com/OJ/gobuster/releases/download/v${GOBUSTER_VERSION}/gobuster_Linux_x86_64.tar.gz"; \
    tar -xzf gobuster.tgz gobuster && mv gobuster /usr/local/bin/gobuster; \
    curl -fsSL -o ferox.zip "https://github.com/epi052/feroxbuster/releases/download/v${FEROX_VERSION}/x86_64-linux-feroxbuster.zip"; \
    unzip -o ferox.zip feroxbuster -d /usr/local/bin && chmod +x /usr/local/bin/feroxbuster; \
    rm -f /tmp/ffuf.tgz /tmp/gobuster.tgz /tmp/ferox.zip

# A small built-in wordlist so dir-busting tools have something to use out of the box.
RUN mkdir -p /usr/share/wordlists && \
    curl -fsSL -o /usr/share/wordlists/common.txt \
      "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Discovery/Web-Content/common.txt" \
    || echo "admin\nlogin\nindex.php\nrobots.txt\n.git\nuploads\napi\nadmin.php" > /usr/share/wordlists/common.txt

# Idle so the container stays up; the agent drives it via `docker exec`.
CMD ["sleep", "infinity"]
