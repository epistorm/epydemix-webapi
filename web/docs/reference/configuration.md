---
sidebar_position: 1
---

# Configuration

The API reads environment variables with the `EPYDEMIX_` prefix. Set them before starting API workers.

| Variable | Default | Description |
|----------|---------|-------------|
| `EPYDEMIX_APP_NAME` | `epydemix WebAPI` | Application name shown in API docs |
| `EPYDEMIX_APP_VERSION` | Installed package version | API version |
| `EPYDEMIX_API_V1_PREFIX` | `/api/v1` | URL prefix for v1 endpoints |
| `EPYDEMIX_WARM_CACHE_ON_STARTUP` | `true` | Pre-load population data at startup |
| `EPYDEMIX_WARM_CACHE_POPULATIONS` | `null` | Population names to pre-load; `null` uses the default list |
| `EPYDEMIX_DEFAULT_NSIM` | `10` | Runs when `simulation.Nsim` is omitted |
| `EPYDEMIX_MAX_NSIM` | `1000` | Maximum accepted runs; cannot exceed 1000 |
| `EPYDEMIX_DEFAULT_DT` | `1.0` | Time step in days when `simulation.dt` is omitted |
| `EPYDEMIX_POPULATION_LOAD_TIMEOUT` | `30.0` | Seconds allowed for a population load; its download process is killed and reaped at the deadline |
| `EPYDEMIX_REQUEST_TIMEOUT` | `60.0` | Simulation execution deadline in seconds, including population loading and child startup; expired CPU workers are killed and reaped |
| `EPYDEMIX_MAX_SIMULATION_STEPS` | `10000` | Maximum internal timeline points and resampled output points |
| `EPYDEMIX_MAX_SIMULATION_CELLS` | `10000000` | Budget for trajectory, quantile and parameter values across time, groups and runs |
| `EPYDEMIX_MAX_CONTACT_CELLS` | `2000000` | Budget for internal time points × age groups² × contact layers, including the combined layer |
| `EPYDEMIX_MCP_ENABLED` | `true` | Expose stateless MCP tools at `/mcp` |

## Simulation execution

Resampling supports positive pandas fixed intervals and calendar offsets such as `D`, `W`, `ME` and `B`. Business-hour offsets `bh` and `cbh`, including their multiples, are rejected because their intraday schedules do not fit the calendar-day output budget.

Each API worker admits one simulation at a time. An overlapping request receives HTTP 503 with `Retry-After: 1`; clients can retry. The worker loads the population from its cache, then starts a disposable simulation process. A deadline produces HTTP 504 and stops the process. Other HTTP endpoints remain responsive while it runs. Process startup adds latency to short simulations.

Requests that exceed allocation budgets receive HTTP 422 before simulation arrays are built. Models support at most 100 age groups, contact layers, compartments, transitions or parameters. Expressions accept at most 2,000 characters and 200 AST nodes; arithmetic must produce finite real numbers. The allocation budgets count values rather than bytes, so actual memory also includes pandas, Python objects and response serialization.

## Cache warming

Warm-up, population detail requests and builtin simulation requests share the same 50-entry population cache per API worker. Cached populations are copied for each model so interventions cannot alter another request's inputs. Age group mapping order is part of the key because it defines the meaning of age-varying parameter vectors. `/populations/cache` reports actual cache entries; bundled metadata alone does not count as a cached population.

```bash
EPYDEMIX_WARM_CACHE_ON_STARTUP=true
EPYDEMIX_WARM_CACHE_POPULATIONS='["United_States", "Italy"]'
```

## MCP workers

MCP uses stateless Streamable HTTP. Initialization returns no session ID, and subsequent requests can reach any worker or replica. No per-client session dictionary is retained. The transport starts and stops with the application's lifespan.
