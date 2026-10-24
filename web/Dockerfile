FROM node:20-alpine
WORKDIR /app
COPY web/package.json ./
RUN npm install
COPY web/ ./
ARG API_INTERNAL=http://api:8000
ENV API_INTERNAL=$API_INTERNAL
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
