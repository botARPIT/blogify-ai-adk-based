# Blogify AI - Production Blog Generation System

Production-grade blog generation system built with Google ADK, featuring multi-agent pipeline with human approval checkpoints.

## Features

- 🤖 **Multi-Agent Pipeline**: Intent → Outline → Research (Tavily) → Writer ⟷ Editor Loop
- 🎯 **LLM as Judge**: Final quality validation using Gemini Pro
- 🔒 **Comprehensive Validation**: Semantic, business rule, and quality checks
- 💰 **Budget Enforcement**: Hard token limits + cost tracking
- 🚦 **Rate Limiting**: Global + per-user limits with Redis
- 🛡️ **Circuit Breakers**: Resilience for external APIs
- 📊 **Monitoring**: Prometheus + Grafana + Datadog ready
- 🔄 **Context Compression**: ADK-based compression before judge

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL (or Neon)
- Redis
- Docker & Docker Compose (optional)

### Installation

```bash
# Clone repository
cd blogify-ai-adk-prod

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e .
```

### Configuration

1. Copy environment template:
```bash
cp .env.dev .env
```

2. Update `.env` with your keys:
- `GOOGLE_API_KEY`: Your Google API key
- `TAVILY_API_KEY`: Your Tavily API key
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis URL

### Database Initialization

```bash
python scripts/init_db.py
```

## Running the Service

### Development

```bash
# Start Redis (if not using docker-compose)
# redis-server &

# Run API
export ENVIRONMENT=dev
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

### With Docker Compose

```bash
docker-compose up
```

This starts:
- API (port 8000)
- PostgreSQL (port 5432)
- Redis (port 6379)
- Prometheus (port 9090)
- Grafana (port 3000)

## API Endpoints

### Health Check
```bash
curl http://localhost:8000/api/health
```

### Chat (General queries)
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
    "message": "Hello, how are you?"
  }'
```

### Generate Blog
```bash
curl -X POST http://localhost:8000/api/blog/generate \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
    "topic": "The Future of AI in Healthcare",
    "audience": "healthcare professionals"
  }'
```

### Approve Stage
```bash
curl -X POST http://localhost:8000/api/blog/approve \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "<session_id>",
    "approved": true
  }'
```

### Metrics
```bash
curl http://localhost:8000/metrics
```

## Architecture

### Agent Pipeline

```
Chatbot (tool: blog_generation)
    ↓
Intent Clarification Loop (max 3 iterations)
    ↓ [Human Approval Required]
Outline Generation
    ↓ [Human Approval Required]
Research (Tavily MCP)
    ↓
Writer ⟷ Editor Loop (max 3 iterations)
    ↓
Context Compression
    ↓
LLM Judge (Gemini Pro)
    ↓
Output Guardrail → Final Blog
```

### Validation Policy

Each agent output undergoes:
1. **Semantic Validation** (e.g., citations match research)
2. **Business Rule Validation** (e.g., word counts)
3. **Quality Checks** (e.g., no repetition)

Max 2 retries per agent on validation failure.

## Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=src tests/

# Run specific test suite
pytest tests/unit/
pytest tests/integration/
```

## Monitoring

### Prometheus Metrics

Access at `http://localhost:9090`

Key metrics:
- `blog_generations_total`
- `agent_token_usage`
- `agent_cost_usd`
- `validation_failures_total`
- `rate_limit_rejections_total`

### Grafana Dashboards

Access at `http://localhost:3000`
- Default credentials: admin/admin

## Environment Configuration

### Development (.env.dev)
- Relaxed rate limits
- Debug logging
- Permissive CORS

### Staging (.env.stage)
- Moderate limits
- Info logging
- Specific domains

### Production (.env.prod)
- Strict limits
- Warning logging
- Explicit CORS whitelist
- Datadog enabled

## Project Structure

```
src/
├── agents/          # All agent definitions
├── api/             # FastAPI routes
├── config/          # Configuration files
├── guards/          # Validation & guardrails
├── models/          # DB models & schemas
├── monitoring/      # Metrics, cost tracking
└── tools/           # Tavily MCP integration

tests/
├── unit/            # Unit tests
├── integration/     # Integration tests
└── eval/            # Evaluation tests

scripts/             # Utility scripts
monitoring/          # Prometheus/Grafana configs
```

## License

MIT
