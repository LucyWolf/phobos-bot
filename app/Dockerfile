FROM python:3.11-slim
# Install docker-compose for in-container update
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates fonts-dejavu-core \
    && ARCH=$(uname -m) \
    && curl -fsSL "https://github.com/docker/compose/releases/download/v2.27.1/docker-compose-linux-${ARCH}" \
       -o /usr/local/bin/docker-compose \
    && chmod +x /usr/local/bin/docker-compose \
    && apt-get remove -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
