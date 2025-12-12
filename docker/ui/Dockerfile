FROM node:20-alpine AS deps

WORKDIR /app
RUN corepack enable

COPY apps/web/package.json /app/package.json
RUN npm install


FROM node:20-alpine AS dev

WORKDIR /app
RUN corepack enable

COPY --from=deps /app/node_modules /app/node_modules
COPY apps/web /app

EXPOSE 3000


FROM node:20-alpine AS runtime

WORKDIR /app
RUN corepack enable

COPY --from=deps /app/node_modules /app/node_modules
COPY apps/web /app

EXPOSE 3000


