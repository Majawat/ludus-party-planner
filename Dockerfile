FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y \
    wget \
    fontconfig \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /usr/share/fonts/truetype/graduate && \
    wget -q -O \
    /usr/share/fonts/truetype/graduate/Graduate-Regular.ttf \
    "https://github.com/google/fonts/raw/main/ofl/graduate/Graduate-Regular.ttf" \
    && fc-cache -fv
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:create_app()"]
