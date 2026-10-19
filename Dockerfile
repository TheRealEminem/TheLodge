# The app on a server (Linux): the same server and web app, without the Mac host. Set APP_ACCESS_TOKEN.
#   docker build -t myapp . && docker run -p 8790:8790 -v myapp-data:/data -e APP_ACCESS_TOKEN=… myapp
FROM node:22-alpine AS web
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app.json vite.config.ts tsconfig.json tailwind.config.js postcss.config.js ./
COPY core/web core/web
COPY identity identity
COPY modules modules
RUN npx vite build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.json VERSION ./
COPY core core
COPY modules modules
COPY --from=web /web/dist dist
ENV APP_DATA_DIR=/data APP_UI_DIR=/app/dist PORT=8790 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8790
HEALTHCHECK CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/app')"
CMD ["sh", "-c", "exec uvicorn core.server.app:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'"]
