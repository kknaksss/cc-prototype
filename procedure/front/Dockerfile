# procedure/front 배포 이미지 — Next.js standalone · arm64 · 비루트 · 포트 3700 (DEC-003)
# 빌드: docker build --platform linux/arm64 --build-arg NEXT_PUBLIC_API_BASE_URL=<back 주소> -t procedure-front .
#   로컬 compose 는 procedure/.env 의 값을 build.args 로 넘긴다. 기본값 없음 — 비면 빌드를 멈춘다(배포 주소로 새지 않게)
# NEXT_PUBLIC_* 는 빌드 때 번들에 박힌다 — 배포 주소가 바뀌면 다시 빌드한다.
# 같은 출처(ingress 가 /api → back)면 SSE(/api/board/stream) · 통역 WS(/api/interpret)도 이 주소로 간다.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL
RUN test -n "$NEXT_PUBLIC_API_BASE_URL" || (echo "빌드 인자 NEXT_PUBLIC_API_BASE_URL 이 비어 있다 — back 주소를 넘겨라" >&2; exit 1)
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3700 \
    HOSTNAME=0.0.0.0
# 비루트 — node 이미지의 node 사용자(uid 1000)
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3700
CMD ["node", "server.js"]
