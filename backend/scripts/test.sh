#!/bin/bash
# Run tests with coverage
# Usage: ./scripts/test.sh

set -e

echo "🧪 Running Blogify AI Tests"
echo ""

# Set test environment
export ENVIRONMENT=test
export GOOGLE_API_KEY=test-key
export TAVILY_API_KEY=test-key
export DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test
export REDIS_URL=redis://localhost:6379/0

# Install test dependencies
echo "📦 Installing test dependencies..."
pip install pytest pytest-asyncio pytest-cov httpx -q

# Run tests
echo "🔬 Running unit tests..."
python -m pytest tests/unit -v --tb=short

echo ""
echo "🔗 Running integration tests..."
python -m pytest tests/integration -v --tb=short

echo ""
echo "📊 Running tests with coverage..."
python -m pytest tests/ -v --cov=src --cov-report=term-missing --cov-report=html

echo ""
echo "✅ All tests complete!"
echo "📄 Coverage report: htmlcov/index.html"
