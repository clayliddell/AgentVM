FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install base dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates gnupg unzip xz-utils \
    qemu-system-x86 qemu-utils qemu-system-gui \
    adb fastboot \
    socat \
    libarchive-tools \
    libvirt0 libpulse0 libsdl2-2.0-0 \
    python3-minimal \
    && rm -rf /var/lib/apt/lists/*

# Add Google cuttlefish repo and install packages
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /usr/share/keyrings/google-linux-signing-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/google-linux-signing-keyring.gpg] \
    https://dl.google.com/linux/cuttlefish/deb/ stable main" \
    > /etc/apt/sources.list.d/cuttlefish.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    cuttlefish-base cuttlefish-user \
    || echo "Cuttlefish packages may not be available, continuing with QEMU" && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash cfuser && \
    echo "cfuser ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/cfuser && \
    mkdir -p /home/cfuser/cuttlefish/images /home/cfuser/cuttlefish/run && \
    chown -R cfuser:cfuser /home/cfuser

WORKDIR /home/cfuser

COPY --chown=cfuser:cfuser entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ADB, VNC-like ports, web viewer
EXPOSE 6520 5555 15550-15555 8443

ENTRYPOINT ["/entrypoint.sh"]
