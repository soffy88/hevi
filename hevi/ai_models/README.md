# Hevi AI Model Integration Layer

This document describes the advanced AI model integration layer implemented in the Hevi project.

## Overview

The Hevi AI Model Integration Layer provides a sophisticated system for managing multiple AI providers with intelligent routing, adaptive learning, and comprehensive orchestration. The system optimizes AI model selection based on cost, quality, performance, and reliability.

## Architecture Components

### 1. AI Model Orchestrator (`orchestrator.py`)
- Discovers and registers existing AI providers
- Maintains model information and capabilities
- Benchmarks model performance
- Tracks health status of all registered models

### 2. Intelligent Routing Service (`routing_service.py`)
- Selects optimal AI models based on various strategies:
  - Cost Optimized: Selects the lowest cost provider meeting requirements
  - Quality Prioritized: Selects the highest quality provider
  - Balanced: Balances cost, quality, and performance
  - Performance Focused: Selects the fastest responding provider
  - Fault Tolerant: Selects the most reliable provider avoiding recent failures
- Estimates costs and response times
- Maintains routing history and analytics

### 3. Adaptive Learning Service (`adaptive_learning.py`)
- Learns from past performance to improve model selection
- Records interactions and performance metrics
- Updates model preferences based on request patterns
- Provides insights and analytics on learning progress
- Supports saving and loading learning state

### 4. Unified AI Service (`unified_service.py`)
- Integrates orchestration, routing, and adaptive learning
- Provides a single interface for AI model execution
- Executes requests with optimal provider selection
- Collects comprehensive analytics
- Supports model quality evaluation

## Usage Examples

### Executing AI Requests

```python
from hevi.ai_models import unified_ai_service, ModelType, RoutingStrategy

# Execute an LLM request with intelligent routing
result = await unified_ai_service.execute_request(
    model_type=ModelType.LLM,
    payload={
        "messages": [{"role": "user", "content": "Hello, world!"}],
        "max_tokens": 100
    },
    strategy=RoutingStrategy.BALANCED,
    quality_threshold=7,
    budget_limit=0.10  # USD
)
```

### Getting Analytics

```python
analytics = await unified_ai_service.get_analytics()
print(f"Success rate: {analytics['execution_stats']['success_rate']}")
print(f"Average execution time: {analytics['execution_stats']['average_execution_time']}")
```

### Model Evaluation

```python
evaluation = await unified_ai_service.evaluate_model_quality(
    provider="openai-gpt4",
    model_type=ModelType.LLM,
    test_cases=[
        {
            "description": "Simple greeting",
            "messages": [{"role": "user", "content": "Say hello"}],
            "expected_output": "Hello"
        }
    ]
)
```

## API Endpoints

The AI model services are exposed through the `/api/ai-models` endpoint:

- `POST /api/ai-models/execute` - Execute AI requests with intelligent routing
- `GET /api/ai-models/analytics` - Get analytics about AI model usage
- `POST /api/ai-models/evaluate-model` - Evaluate model quality
- `POST /api/ai-models/optimize-request` - Optimize model selection for request patterns
- `GET /api/ai-models/health` - Health check for AI services

## Key Features

### Intelligent Routing Strategies
- **Cost Optimized**: Automatically selects the most economical provider
- **Quality Prioritized**: Selects the highest quality provider
- **Balanced**: Considers cost, quality, and performance equally
- **Performance Focused**: Selects the fastest responding provider
- **Fault Tolerant**: Avoids providers with recent failures

### Adaptive Learning
- Continuous learning from execution results
- Pattern recognition for request optimization
- Quality scoring and feedback incorporation
- Performance metric tracking

### Multi-Model Support
- LLM (Large Language Models)
- VLM (Vision-Language Models)
- Audio Generation
- Video Generation
- Image Generation

### Cost Optimization
- Real-time cost estimation
- Budget limit enforcement
- Provider cost comparison
- Economic model selection

### Reliability Features
- Failure detection and avoidance
- Health monitoring
- Fallback mechanisms
- Performance tracking

## Integration Points

The AI model integration layer works seamlessly with the existing Hevi architecture:
- Integrates with the existing provider registry
- Works with the microservices architecture
- Compatible with existing authentication
- Follows existing error handling patterns

## Configuration

The AI model services use the existing Hevi configuration system and adapt to the registered providers in the system.

## Benefits

1. **Optimization**: Automatically selects the best model for each request based on multiple factors
2. **Reliability**: Avoids failing providers and maintains service availability
3. **Cost Efficiency**: Optimizes for cost while maintaining quality requirements
4. **Scalability**: Supports multiple providers and can easily incorporate new ones
5. **Learning**: Continuously improves model selection based on actual performance
6. **Flexibility**: Supports various routing strategies for different use cases