FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for Chrome + selenium/uc stability + virtual display (Xvfb)
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg \
      fonts-liberation \
      xauth xvfb \
      libasound2 libatk-bridge2.0-0 libatk1.0-0 libc6 libcairo2 libcups2 libdbus-1-3 \
      libdrm2 libexpat1 libgbm1 libglib2.0-0 libgtk-3-0 libnspr4 libnss3 libpango-1.0-0 \
      libpangocairo-1.0-0 libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 \
      libxdamage1 libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 libxshmfence1 \
      libxss1 libxtst6 lsb-release xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome Stable
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python -m pip install -r /app/requirements.txt

COPY . /app

# Runtime defaults for container
ENV IN_DOCKER=1 \
    CHROME_HEADLESS=0 \
    CHROME_PROFILE_DIR=/data/chrome_profile \
    DISPLAY=:99

VOLUME ["/data"]

# Start virtual display, then bot (X11 server uchun -ac: access kontrol o'chiq)
CMD ["/bin/sh", "-c", "Xvfb :99 -screen 0 1024x768x24 -ac > /dev/null 2>&1 & sleep 2 && python main.py"]

