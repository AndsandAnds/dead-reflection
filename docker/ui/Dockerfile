FROM node:20-alpine

WORKDIR /app

RUN corepack enable

COPY apps/web/package.json /app/package.json
RUN npm install

COPY apps/web /app

EXPOSE 3000


