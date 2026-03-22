# System Architecture

## High-Level Architecture

The Blogify AI system is built on a microservices-like architecture using FastAPI for the core service, Celery-like background workers for asynchronous processing, and Google's Agent Development Kit (ADK) for AI orchestration.

```mermaid
graph TB
    subgraph "External World"
        User[User / Client App]
        Auth[Auth Service]
        Gemini[Google Gemini API]
        Tavily[Tavily Search API]
    end

    subgraph "Blogify AI Cluster"
        LB[Load Balancer]
        
        subgraph "API Layer"
            API[FastAPI Service]
            AuthMiddleware[Auth Middleware]
            RateGuard[Rate Limit Guard]
            SessionStore[Session Store]
            
            API --> AuthMiddleware
            AuthMiddleware --> RateGuard
            RateGuard --> SessionStore
        end
        
        subgraph "Processing Layer"
            Worker[Background Worker]
            Executor[Stage Executor]
            Pipeline[Blog Generation Pipeline]
            
            subgraph "Active Agents"
                Intent[Intent Agent]
                Outline[Outline Agent]
                Research[Research Agent]
                Writer[Writer Agent]
            end
        end
        
        subgraph "Data Storage"
            Redis[Redis Cache & Queue]
            DB[(PostgreSQL)]
        end
        
        subgraph "Observability"
            Prometheus[Prometheus]
            Grafana[Grafana]
        end
    end

    %% Flow Connections
    User -->|HTTPS POST /generate| LB
    LB --> API
    
    %% API Dependencies
    API -->|Rate Check| Redis
    API -->|Create Record| DB
    API -->|Enqueue Job| Redis
    API -.->|Validate| Auth
    
    %% Async Processing
    Redis -->|Dequeue Job| Worker
    Worker -->|Run Stage| Executor
    Executor -->|Invoke| Pipeline
    
    %% Pipeline Execution
    Pipeline --> Intent
    Pipeline --> Outline
    Pipeline --> Research
    Pipeline --> Writer
    
    %% External Calls
    Intent -.->|LLM| Gemini
    Outline -.->|LLM| Gemini
    Writer -.->|LLM| Gemini
    Research -.->|Search| Tavily
    
    %% Persistence
    Executor -->|Save Stage State| DB
```

## Blog Generation Pipeline Flow

The system uses a fully automated, multi-stage pipeline executed by background workers. Human-in-the-Loop (HITL) features are deprecated; the process runs from intent to completion without intervention.

```mermaid
sequenceDiagram
    participant User
    participant API
    participant Redis
    participant Worker
    participant DB
    participant Agents as Pipeline/Agents

    User->>API: POST /blogs/generate
    activate API
    API->>Redis: Check Rate Limit & Concurrency
    API->>DB: Create Blog Record (status=queued)
    API->>Redis: Enqueue Job
    API-->>User: 202 Accepted (task_id)
    deactivate API
    
    loop Polling
        User->>API: GET /blog/task/{task_id}
        API->>Redis: Get Status
        API-->>User: Status (pending/processing/completed)
    end

    Redis->>Worker: Dequeue Job
    activate Worker
    
    note right of Worker: Stage 1: Intent
    Worker->>Agents: Run Intent Agent
    Agents-->>Worker: Topic Analysis
    Worker->>DB: Save Stage Result
    
    note right of Worker: Stage 2: Outline
    Worker->>Agents: Run Outline Agent
    Agents-->>Worker: Structured Outline
    Worker->>DB: Save Stage Result

    note right of Worker: Stage 3: Research
    Worker->>Agents: Run Research Agent
    Agents-->>Worker: Sources & Summary
    Worker->>DB: Save Stage Result

    note right of Worker: Stage 4: Writing
    Worker->>Agents: Run Writer Agent
    Agents-->>Worker: Final Blog Content
    Worker->>DB: Save Blog (status=completed)
    
    deactivate Worker
```

## Core Components

### 1. API Service (`src/api`)
- **Role**: Entry point and control plane.
- **Key Features**: 
  - **Backpressure**: Rejects requests when queue depth or concurrency limits are exceeded (503 Service Unavailable).
  - **Idempotency**: Prevents duplicate processing using `Idempotency-Key` headers.
  - **Stateless**: No long-running jobs in the API layer; all heavy lifting is offloaded.

### 2. Background Worker (`src/workers`)
- **Role**: Asynchronous execution of blog generation.
- **Stage Executor**: Manages the state machine transitions (`Intent` -> `Outline` -> `Research` -> `Writing`).
- **Resilience**: Handles job visibility timeouts, retries with exponential backoff, and crash recovery.

### 3. Blog Generation Pipeline (`src/agents`)
- **Role**: Deterministic orchestration of AI agents.
- **Agents**:
  - **Intent Agent**: Validates topic clarity.
  - **Outline Agent**: Structures the blog post.
  - **Research Agent**: Uses Tavily to fetch real-time data.
  - **Writer Agent**: Synthesizes outline and research into final markdown.
  *Note: The `Editor` agent exists in the codebase but is currently inactive in the production pipeline.*

### 4. Infrastructure
- **Redis**: 
  - Token bucket rate limiting.
  - Job queue (List/Stream).
  - Session/Idempotency storage.
- **PostgreSQL**: 
  - relational data (Users, Blogs).
  - JSONB storage for intermediate stage results.
