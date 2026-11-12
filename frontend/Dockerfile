# AgentGuard dashboard image. Multi-stage: build the static bundle, then serve
# it with a lightweight static file server that also proxies /api to the backend.
FROM node:22-alpine AS builder

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Runtime: nginx serves the SPA and reverse-proxies the API.
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 8080

# nginx's docker entrypoint runs envsubst over /etc/nginx/templates/*.template
# using variables from the environment, writing the result to
# /etc/nginx/conf.d/. BACKEND_HOST comes from docker-compose.
ENV BACKEND_HOST=backend

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
