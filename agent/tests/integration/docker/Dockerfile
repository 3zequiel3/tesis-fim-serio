# Disposable test image for agent/tests/integration/test_install_sh_container.py
# (D56/RN-150, design D-7). NOT used anywhere in production — only to run
# agent/install.sh as root inside a throwaway container with a systemctl
# shim standing in for real systemd (task 9.8).
FROM python:3.13-slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends procps openssl && \
    rm -rf /var/lib/apt/lists/*
COPY systemctl /usr/local/bin/systemctl
RUN chmod 0755 /usr/local/bin/systemctl
WORKDIR /workspace
CMD ["sleep", "infinity"]
