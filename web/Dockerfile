# Build context is web/ (see docker-compose.yml: `build: ./web`). Two
# stages: build the Vite SPA with Node, then serve the compiled static
# output from Caddy -- Caddy also does TLS + reverse-proxying to the API
# per the Caddyfile mounted alongside this image (see docker-compose.yml
# and ./Caddyfile at the repo root).
#
# NOTE for whoever lands the frontend (tasks 14-21): this Dockerfile builds
# against whatever `web/` contains -- `npm run build`'s output directory
# must be `dist/` (Vite's default, and what's gitignored at the repo root)
# to match the `COPY --from=build /app/dist /srv` line below. If the build
# tool or output directory changes, update that COPY path to match.
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
