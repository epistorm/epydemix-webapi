---
slug: /
sidebar_position: 1
---

# Introduction

epydemix Web API is a REST API for running epidemic simulations powered by [epydemix](https://github.com/epistorm/epydemix).

## Overview

The API exposes epydemix's simulation engine over HTTP. You can run compartmental models (SIR, SEIR, SIS) against built-in population data by sending a single JSON request. No Python environment required on the client side.

## How it works

1. Pick a model preset and population
2. POST a simulation request with your parameters
3. Get back compartment trajectories for each simulation run

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | [`/api/v1/simulations`](/api-reference) | Run a simulation |
| GET | [`/api/v1/populations`](/api-reference) | List available populations |
| GET | [`/api/v1/populations/{name}`](/api-reference) | Get population details |
| GET | [`/api/v1/populations/{name}/contacts`](/api-reference) | Get contact matrices |
| GET | [`/api/v1/models/presets`](/api-reference) | List model presets |
| GET | [`/api/v1/health`](/api-reference) | Health check |

The [API Reference](/api-reference) has interactive docs where you can explore schemas and send requests directly.
