FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y \
    wget \
    fontconfig \
    fonts-liberation \
    libgl1 \
    libglu1-mesa \
    libxrender1 \
    libxext6 \
    libsm6 \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /usr/share/fonts/truetype/graduate && \
    wget -q -O \
    /usr/share/fonts/truetype/graduate/Graduate-Regular.ttf \
    "https://github.com/google/fonts/raw/main/ofl/graduate/Graduate-Regular.ttf" \
    && fc-cache -fv
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x /app/docker-entrypoint.sh
ENV FLASK_APP=app
EXPOSE 8000
# The entrypoint applies DB migrations (idempotent) before starting gunicorn, so a
# fresh deployment comes up with a valid schema instead of 500ing on missing tables.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
