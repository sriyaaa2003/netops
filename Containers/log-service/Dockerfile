FROM node:18-alpine

WORKDIR /app

COPY package.json .
RUN npm install --omit=dev

COPY server.js .

RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser

EXPOSE 4000

CMD ["node", "server.js"]
