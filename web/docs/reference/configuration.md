---
sidebar_position: 1
---

# Configuration

The API reads configuration from environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `epydemix WebAPI` | Application name shown in API docs |
| `APP_VERSION` | `0.1.1` | API version |
| `API_V1_PREFIX` | `/api/v1` | URL prefix for all v1 endpoints |
| `WARM_CACHE_ON_STARTUP` | `false` | Pre-load population data at startup |
| `WARM_CACHE_POPULATIONS` | `[]` | List of population names to pre-load |

## Cache warming

Population data is loaded on first request by default. Setting `WARM_CACHE_ON_STARTUP=true` pre-loads specified populations at startup, which reduces latency on the first request for those populations.

```bash
WARM_CACHE_ON_STARTUP=true
WARM_CACHE_POPULATIONS=["United_States", "Italy"]
```
