FROM python:3.11-slim
# Install docker-compose for in-container update, plus a build toolchain so
# pip can compile psutil/Pillow/bcrypt from source on architectures (notably
# 32-bit Raspberry Pi OS / armv7l, and any arch without a prebuilt manylinux
# wheel) where no prebuilt wheel exists. gcc+libjpeg-dev+zlib1g-dev cover
# psutil/Pillow's C extensions, rustc+cargo cover bcrypt's Rust extension.
# Kept installed (not removed) since the later pip install layer needs them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         curl git ca-certificates fonts-dejavu-core \
         gcc libjpeg-dev zlib1g-dev rustc cargo \
    && ARCH=$(uname -m) \
    && case "$ARCH" in \
         armv7l) COMPOSE_ARCH=armv7 ;; \
         armv6l) COMPOSE_ARCH=armv6 ;; \
         *)      COMPOSE_ARCH=$ARCH ;; \
       esac \
    && curl -fsSL "https://github.com/docker/compose/releases/download/v2.27.1/docker-compose-linux-${COMPOSE_ARCH}" \
       -o /usr/local/bin/docker-compose \
    && chmod +x /usr/local/bin/docker-compose \
    && apt-get remove -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* \
    && git config --global --add safe.directory /repo
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
