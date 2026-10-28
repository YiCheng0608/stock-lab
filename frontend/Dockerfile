# The frontend image (#334). The build context is frontend/ (frontend/.dockerignore):
#
#   docker build -t stock-lab-web frontend                 # nginx: the built pages, /api to the api
#   docker build --target dev -t stock-lab-web-dev frontend   # pnpm dev, test:ci and build
#
# The default (last) stage serves the production build with nginx and reverse proxies /api
# to API_UPSTREAM (default api:8000, the compose service name, #335); docker/nginx.conf.template
# holds the rules. Versions follow CI (node 22, pnpm 10.18.3, the lock file); the base images
# are pinned by tag and digest, node to the same one as backend/Dockerfile.
ARG NODE_IMAGE=node:22.23.4-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da
ARG NGINX_IMAGE=nginx:1.28.3-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236

FROM ${NODE_IMAGE} AS deps
ARG PNPM_VERSION=10.18.3
RUN npm install --global --no-fund --no-audit "pnpm@${PNPM_VERSION}" \
    && npm cache clean --force \
    && mkdir -p /app/frontend \
    && chown node:node /app/frontend
# The image's node user (uid 1000): files the dev container writes into a bind-mounted
# checkout on a Linux host are not root's.
USER node
WORKDIR /app/frontend
COPY --chown=node:node package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

# pnpm dev on 0.0.0.0 so a published port reaches it; compose bind mounts the sources over
# these and sets VITE_API_BASE (frontend/README.md). test:ci and build run here too.
FROM deps AS dev
COPY --chown=node:node . .
EXPOSE 5173
CMD ["pnpm", "run", "dev", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]

# The pages call the API on their own origin: nginx forwards /api with the browser's Host.
FROM dev AS build
ARG VITE_API_BASE=/api
RUN VITE_API_BASE="${VITE_API_BASE}" pnpm run build

FROM ${NGINX_IMAGE} AS web
# The image's entrypoint fills ${...} in /etc/nginx/templates/*.template from these (only
# variables that are set, so nginx's own $http_host stays) and, with LOCAL_RESOLVERS set,
# exports NGINX_LOCAL_RESOLVERS from /etc/resolv.conf: the upstream name is looked up per
# request, so nginx starts before the api is up and follows a restarted api container.
ENV API_UPSTREAM=api:8000 \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1
COPY docker/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/frontend/dist /usr/share/nginx/html
EXPOSE 80
