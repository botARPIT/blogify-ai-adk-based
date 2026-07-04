# Build and run the Vite React app for local development
FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package.json package-lock.json* ./

# Install dependencies using npm
RUN npm ci

# Copy application source code
COPY . .

# Expose port 3000 (which is mapped to 3001 in docker-compose.local.yml)
EXPOSE 3000

# Start Vite dev server on port 3000, listening on all interfaces
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
