# ─── Stage 1: build ───────────────────────────────────────────────────────────
FROM node:22-alpine AS build

RUN corepack enable

WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

# ─── Stage 2: serve ───────────────────────────────────────────────────────────
FROM nginx:alpine AS serve

COPY --from=build /app/dist /usr/share/nginx/html

# Plantillas versionadas por modo de CONSOLE_TLS_MODE (D55/RN-149, change 52):
# el hook de abajo decide en tiempo de arranque cuál se copia como
# /etc/nginx/conf.d/default.conf — NO se copia ninguna acá, para no dejar un
# default.conf obsoleto si el hook falla antes de reemplazarlo.
COPY nginx/ /etc/nginx/fim-console/
COPY docker-entrypoint.d/40-fim-console-tls.sh /docker-entrypoint.d/40-fim-console-tls.sh

EXPOSE 80 443

CMD ["nginx", "-g", "daemon off;"]
