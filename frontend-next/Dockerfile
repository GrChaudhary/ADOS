# ADOS frontend — Next.js 16 (App Router), built as a standalone server.
#
# Build:  docker build -t ados-frontend frontend-next
# Run:    docker compose up  (see ../docker-compose.yml)

# ---------------------------------------------------------------------------
# deps — install once, cached until package-lock.json changes
# ---------------------------------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---------------------------------------------------------------------------
# builder
# ---------------------------------------------------------------------------
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* is inlined into the browser bundle at build time, not read at
# runtime, so it has to be a build arg. This one is the origin the *browser*
# opens the SSE stream against (src/lib/api.ts) — it must be reachable from
# the user's machine, not from inside the compose network. That's why it
# defaults to localhost:8000 and not http://backend:8000: the server-side
# rewrite proxy uses ADOS_BACKEND_ORIGIN for the in-network hop instead.
ARG NEXT_PUBLIC_ADOS_BACKEND_ORIGIN=http://localhost:8000
ENV NEXT_PUBLIC_ADOS_BACKEND_ORIGIN=${NEXT_PUBLIC_ADOS_BACKEND_ORIGIN}

RUN npm run build

# ---------------------------------------------------------------------------
# runner — only the standalone output and static assets
# ---------------------------------------------------------------------------
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 10001 nodejs && adduser -u 10001 -G nodejs -S nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD wget -qO- http://localhost:3000/ >/dev/null 2>&1 || exit 1

CMD ["node", "server.js"]
