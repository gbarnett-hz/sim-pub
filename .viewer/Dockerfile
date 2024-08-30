FROM node:alpine3.20 AS builder

WORKDIR /sim-viewer
COPY src src
COPY *.json .

RUN npm i --dev && npm i && npm run build

FROM node:alpine3.20

WORKDIR /sim-viewer
COPY --from=builder ./sim-viewer/dist ./dist
COPY *.json .
RUN npm i --production

ENTRYPOINT [ "node","/sim-viewer/dist/main.js" ]
