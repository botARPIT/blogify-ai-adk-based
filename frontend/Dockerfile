# Optional Vite development image; production frontend deployment uses Vercel.
FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package.json package-lock.json* ./

# Install dependencies using npm
RUN npm ci

# Copy application source code
COPY . .

# Expose the Vite development server
EXPOSE 3000

# Start Vite dev server on port 3000, listening on all interfaces
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
