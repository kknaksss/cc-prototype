# cc/front 배포 이미지 — Next.js standalone · arm64 · 비루트 · 포트 3600 (DEC-003)
# 빌드: docker build --platform linux/arm64 --build-arg NEXT_PUBLIC_API_BASE_URL=https://ccc.medisolveai.xyz -t cc-front .
# NEXT_PUBLIC_* 는 빌드 때 번들에 박힌다 — 배포 주소가 바뀌면 다시 빌드한다.
# 같은 출처(ingress 가 /api → back)라 통역 WS 는 이 값의 http→ws(https→wss) + /api/interpret 로 간다.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL=https://ccc.medisolveai.xyz
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3600 \
    HOSTNAME=0.0.0.0
# 비루트 — node 이미지의 node 사용자(uid 1000)
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3600
CMD ["node", "server.js"]
