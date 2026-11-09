# Build from the repository root: docker build -f web/Dockerfile .
FROM node:22-alpine AS build
WORKDIR /repo
COPY packages/api-client packages/api-client
COPY web/package.json web/package-lock.json web/
RUN cd web && npm ci --no-audit --no-fund
COPY web web
# Empty NEXT_PUBLIC_API_URL + API_INTERNAL_URL: the browser calls /api/v1 on the web origin and the
# web server forwards it to the API. Set NEXT_PUBLIC_API_URL instead to call a public API URL directly.
ARG NEXT_PUBLIC_API_URL=
ARG API_INTERNAL_URL=http://api:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL API_INTERNAL_URL=$API_INTERNAL_URL NEXT_TELEMETRY_DISABLED=1
RUN cd web && npx next build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /repo/web/.next/standalone ./
COPY --from=build /repo/web/.next/static ./web/.next/static
USER node
EXPOSE 3000
CMD ["node", "web/server.js"]
