# conftest for smoke tests — sets minimal env vars
import os

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("GOOGLE_API_KEY", "smoke-test-key")
os.environ.setdefault("TAVILY_API_KEY", "smoke-test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
