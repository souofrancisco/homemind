# syntax=docker/dockerfile:1
FROM node:22.12-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --fetch-retries=5 --fetch-retry-mintimeout=2000
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]
