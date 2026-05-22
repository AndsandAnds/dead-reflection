# Base image pinned by digest to immobilize against tag mutation. To refresh,
# `docker pull node:20-alpine` and copy the printed Digest below into all
# three stages (they must match for layer reuse).
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS deps

WORKDIR /app
RUN corepack enable

COPY apps/web/package.json /app/package.json
RUN npm install


FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS dev

WORKDIR /app
RUN corepack enable

COPY --from=deps /app/node_modules /app/node_modules
COPY apps/web /app

EXPOSE 3000


FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS runtime

WORKDIR /app
RUN corepack enable

COPY --from=deps /app/node_modules /app/node_modules
COPY apps/web /app

EXPOSE 3000


