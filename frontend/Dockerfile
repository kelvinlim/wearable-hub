# Build the Vite app, then serve the static bundle via nginx (which also reverse-proxies the
# backend API so the SPA stays same-origin — no CORS).
FROM node:20-alpine AS build
WORKDIR /app
# `npm ci` installs from the committed lockfile, so every image build is reproducible.
# (A flaky `npm install` once dropped `scheduler` — react-dom's runtime dep — and Rollup
# silently shipped a bare `import "scheduler"`, breaking the app in the browser.)
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
# Runs before nginx starts (via the base image's /docker-entrypoint.sh); templates the
# container's DNS resolver IP into nginx.conf so proxy_pass survives backend restarts.
COPY 30-set-resolver.sh /docker-entrypoint.d/30-set-resolver.sh
RUN chmod +x /docker-entrypoint.d/30-set-resolver.sh
EXPOSE 80
