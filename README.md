# vLLM

[vLLM](https://docs.vllm.ai/) hosting setup configured to work in our setup with
Traefik and nginx to limit exposed end-points.

## Security

Bearer-token auth is enforced at nginx via a tiny sidecar (`authz`) that checks
the client token against `.docker/authz/api_keys.txt`. Multiple keys are
supported — one per line — and add/revoke takes effect on the next request
without restarting the stack. nginx then rewrites the `Authorization` header
to the upstream `VLLM_API_KEY`, so the upstream key is never exposed to
clients.

On first setup, copy the template:

```
cp .docker/authz/api_keys.txt.example .docker/authz/api_keys.txt
```

Network access is still expected to be gated by server firewalls and Traefik.
