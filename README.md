# vLLM embedding service

Docker Compose stack hosting two [vLLM](https://docs.vllm.ai/) embedding
models and one reranker behind a single nginx reverse proxy, integrated
with Traefik for routing and TLS. All three models share one GPU. The
nginx layer enforces multi-key bearer-token auth via a small sidecar;
Traefik handles HTTPS.

| Route prefix | Model                                       | Service          |
|--------------|---------------------------------------------|------------------|
| `/`          | `intfloat/multilingual-e5-large`            | `vllm-e5`        |
| `/bge/`      | `BAAI/bge-m3` (`--convert embed`)           | `vllm-bge`       |
| `/rerank/`   | `BAAI/bge-reranker-v2-m3` (`--convert classify`) | `vllm-reranker` |

The two embedding services expose the standard OpenAI-compatible
endpoints (`/v1/embeddings`, `/v1/models`, etc.). The reranker exposes
`/v1/score` (vLLM-native) and `/v1/rerank` (Cohere-compatible).
`/metrics` (e5), `/bge/metrics` (bge), and `/rerank/metrics` (reranker)
are exposed behind an IP allowlist for Prometheus scraping.

## Requirements

- Docker Engine with Compose v2
- For the server overlay: an NVIDIA GPU and the
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
- A Traefik instance reachable via the external Docker network named
  `frontend` (the stack attaches to it; it is not created here)

## Quick start

```bash
# Config
cp .env.example .env
$EDITOR .env                                  # set HUGGING_FACE_HUB_TOKEN, domains, VLLM_API_KEY

# Client API keys (one bearer token per line; see format below)
cp .docker/authz/api_keys.txt.example .docker/authz/api_keys.txt
$EDITOR .docker/authz/api_keys.txt

# Local
docker compose up -d

# Dev (adds Traefik basic-auth middleware)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Production (GPU reservation + HTTPS redirect; requires COMPOSE_SERVER_DOMAIN in .env)
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d
```

First boot downloads the models into `.docker/data/vllm/` — this can take
several minutes per model.

## Example requests

```bash
# e5 — multilingual-e5-large
curl -s "https://$COMPOSE_DOMAIN/v1/embeddings" \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "intfloat/multilingual-e5-large",
    "input": "Hej verden"
  }'

# bge — BAAI/bge-m3 (note the /bge/ prefix; nginx strips it before proxying)
curl -s "https://$COMPOSE_DOMAIN/bge/v1/embeddings" \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "BAAI/bge-m3",
    "input": ["Hej verden", "Hello, world"]
  }'

# reranker — BAAI/bge-reranker-v2-m3 (Cohere-compatible /v1/rerank: returns sorted indices + scores)
curl -s "https://$COMPOSE_DOMAIN/rerank/v1/rerank" \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "BAAI/bge-reranker-v2-m3",
    "query": "What is the capital of France?",
    "documents": ["Paris is the capital of France.", "Berlin is the capital of Germany."]
  }'

# reranker — vLLM-native /v1/score (raw scores, unsorted; takes text_1/text_2)
curl -s "https://$COMPOSE_DOMAIN/rerank/v1/score" \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "BAAI/bge-reranker-v2-m3",
    "text_1": "What is the capital of France?",
    "text_2": ["Paris is the capital of France.", "Berlin is the capital of Germany."]
  }'
```

`$CLIENT_TOKEN` is the token part of a line in
`.docker/authz/api_keys.txt`; the `# name <email>` suffix is metadata and
is not part of the token.

The response shape matches the OpenAI embeddings API:
`{"data": [{"embedding": [...], "index": 0}, ...], "model": "...", "usage": {...}}`.

## Configuration

All environment configuration lives in `.env` (start from `.env.example`):

| Variable                             | Purpose                                                                 |
|--------------------------------------|-------------------------------------------------------------------------|
| `COMPOSE_PROJECT_NAME`               | Used for container names and Traefik router names                       |
| `COMPOSE_DOMAIN`                     | Host for the local/dev Traefik router                                   |
| `COMPOSE_SERVER_DOMAIN`              | Host for the production Traefik router (used by `docker-compose.server.yml`) |
| `HUGGING_FACE_HUB_TOKEN`             | Required for HuggingFace model downloads                                |
| `VLLM_E5_MODEL` / `VLLM_E5_OPTIONS` / `SHM_E5_SIZE` | Model ID, engine args, shared memory for `vllm-e5`           |
| `VLLM_BGE_MODEL` / `VLLM_BGE_OPTIONS` / `SHM_BGE_SIZE` | Model ID, engine args, shared memory for `vllm-bge`       |
| `VLLM_RERANKER_MODEL` / `VLLM_RERANKER_OPTIONS` / `SHM_RERANKER_SIZE` | Model ID, engine args, shared memory for `vllm-reranker` |
| `VLLM_API_KEY`                       | Upstream key between nginx and vLLM. nginx rewrites the client `Authorization` to this value before proxying, so clients never see it. |
| `NGINX_ALLOW_METRICS_IP`             | IP allowed to hit `/metrics`, `/bge/metrics`, and `/rerank/metrics`     |

All three models run on the same GPU, so `--gpu-memory-utilization` must
be set per model in `VLLM_*_OPTIONS` to avoid OOM (the example file uses
`0.30` each, totaling `0.90` and leaving 10% headroom). See the
[vLLM engine args reference](https://docs.vllm.ai/en/latest/models/engine_args.html).

> **Upgrading from a two-service deployment:** the example previously
> used `--gpu-memory-utilization 0.45` for e5 and bge. After pulling
> this change you must lower both to `0.30` in your existing `.env`,
> otherwise the third service will OOM at boot (0.45 + 0.45 + 0.30 >
> 1.0). The reranker is a cross-encoder served via `--convert classify`;
> clients should hit `/rerank/v1/rerank` (Cohere format) or
> `/rerank/v1/score` (vLLM-native).

> **Note:** `.env.example` does not include `COMPOSE_SERVER_DOMAIN`; add
> it to your `.env` if you intend to use `docker-compose.server.yml`.

## Authentication

Client bearer tokens are stored in `.docker/authz/api_keys.txt` (gitignored),
one per line, with optional trailing metadata after `#`:

```
tok_abc123 # Alice <alice@example.com>
tok_def456 # Bob <bob@example.com>
```

On each request nginx performs an `auth_request` to a tiny Python sidecar
(`authz`) that reads this file and returns 204/401. Successful requests
have their `Authorization` rewritten to `Bearer $VLLM_API_KEY` before
reaching vLLM, so the upstream key is never exposed to clients.

**Add or revoke a key:** edit `.docker/authz/api_keys.txt`. Changes take
effect on the next request — no restart required. Prefer an atomic
replacement (`mv tmp api_keys.txt`) over in-place editing to avoid a
brief window where the file is empty.

The authz sidecar logs one line per auth decision to stdout:

```
204 192.0.2.10 Alice <alice@example.com>
401 192.0.2.99 -
```

Tokens themselves are never logged, on either success or failure.

## Compose overlays

| File                        | Role            | Adds                                                             |
|-----------------------------|-----------------|------------------------------------------------------------------|
| `docker-compose.yml`        | Base            | nginx, three vllm services, authz sidecar, networks, Traefik labels on `COMPOSE_DOMAIN` |
| `docker-compose.dev.yml`    | Dev overlay     | Traefik `ITKBasicAuth@file` middleware in front of nginx        |
| `docker-compose.server.yml` | Server overlay  | `restart: unless-stopped`, NVIDIA GPU reservations, HTTPS+redirect Traefik labels on `COMPOSE_SERVER_DOMAIN` |

## Operations

```bash
# Tail auth decisions (who's hitting what)
docker compose logs -f authz

# Tail vLLM output (model loading, warnings)
docker compose logs -f vllm-e5 vllm-bge vllm-reranker

# GPU usage on a server
nvidia-smi dmon -s u

# Restart just the authz sidecar after changing app.py
docker compose restart authz
```

## Security notes

- No authentication is provided by the vLLM containers directly; the
  `VLLM_API_KEY` they enforce is only reachable via nginx, which itself
  gates all proxied paths through authz. Direct access to the vLLM
  containers from outside the `app` Docker network is not expected.
- `/metrics` endpoints are gated **by IP only**, not by bearer token.
  Keep `NGINX_ALLOW_METRICS_IP` tight — vLLM metrics can reveal model
  names, request latencies, and GPU memory usage.
- Network access to nginx is still expected to be gated by the server's
  firewall and Traefik entrypoints.
- `.docker/authz/api_keys.txt` contains credentials. Treat it
  accordingly (backups, access control on the host, etc.).

## See also

- `CLAUDE.md` — architecture details, file-by-file breakdown, and
  development notes for contributors and AI coding assistants.
- [vLLM docs](https://docs.vllm.ai/)
- [OpenAI embeddings API reference](https://platform.openai.com/docs/api-reference/embeddings)
