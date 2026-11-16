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
    && rm -rf /var/lib/apt/lists/*

# Zwei Dinge fuer den Betrieb ohne root:
#
# 1. safe.directory per --system statt --global. --global schreibt nach /root/.gitconfig
#    und gilt damit nur fuer root. Seit der Bot als eigener Benutzer laeuft, wuerde git im
#    eingehaengten /repo sonst "dubious ownership" melden - das Update ueber das Dashboard
#    waere tot, ohne dass man dem Fehlertext ansaehe, woran es liegt.
# 2. Der Benutzer selbst. 1000, weil das auf den allermeisten Wirten der erste echte
#    Benutzer ist und die eingehaengten Ordner damit ohne Umrechnen passen; abweichende
#    Nummern gehen zur Laufzeit ueber PUID/PGID (siehe entrypoint.sh).
RUN git config --system --add safe.directory /repo \
    && git config --system --add safe.directory /app \
    && useradd --uid 1000 --user-group --create-home --home-dir /home/phobos \
         --shell /usr/sbin/nologin phobos
ENV HOME=/home/phobos
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Ueber "sh <datei>" aufgerufen, nicht direkt: /app wird zur Laufzeit vom Wirt
# ueberblendet, und ob das Ausfuehrbar-Bit dort ueberlebt (Windows, ein entpacktes
# Archiv, ein anderes Dateisystem), ist nicht garantiert. Der Inhalt reicht.
ENTRYPOINT ["/bin/sh", "/app/entrypoint.sh"]
