# Playwright'ın resmi imajı Chromium + bağımlılıklarıyla gelir (hepsiemlak için gerekli).
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV TZ=Europe/Istanbul
VOLUME ["/app/data"]
CMD ["python", "main.py", "run"]
