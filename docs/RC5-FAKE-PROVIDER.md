# RC5 deterministic fake provider

The qualification fake provider is a separate ASGI service, not a route in
the production API. It is enabled only with both runtime values:

```text
HEVI_DEPLOY_ENV=staging
HEVI_FAKE_PROVIDER_ENABLED=true
```

Any other combination, including production with the enable flag set, returns
404. It has no credentials and makes no outbound provider calls.

Run the exact candidate image in an isolated staging network:

```bash
HEVI_API_IMAGE=hevi-api:v0.1.0-rc5-<sha7> \
  docker compose -f deploy/docker-compose-fake-provider.staging.yml up -d
```

The endpoint is `POST /v1/fake-provider/generate` and accepts an explicit
`scenario` of `success`, `timeout`, `rate_limit`, `server_error`, `malformed`,
`slow`, or `stream_abort`. Delay scenarios accept bounded `delay_ms` (0–5000).
`stream_abort` emits a partial SSE response without the terminal `[DONE]`
marker so a client can verify that streaming is not retried unsafely.
