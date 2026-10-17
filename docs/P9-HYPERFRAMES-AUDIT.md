# P9.1.e — HyperFrames Runtime Audit

**Finding: the CLI render path does not terminate. The provider still renders, via its
ffmpeg fallback. HyperFrames is QUALIFIED — through the fallback, and honestly labelled
as such.**

## 1. Runtime identity

| | |
|---|---|
| `provider_id` | `hyperframes` |
| binary | `~/.nvm/versions/node/v26.4.0/bin/hyperframes` (resolved by the provider's own `detect_hyperframes_bin`, never by pattern) |
| version | `0.8.111` |
| entrypoint | `hyperframes render <workspace> -o <out> -f <fps> -q <quality> --quiet` |
| `runtime_class` | `LOCAL_PROCESS` |
| `provider_kind` | `VIDEO` |
| credentials | none required |

## 2. The defect

`hyperframes render` was observed **exceeding both 90s and 600s without completing**.

```
timeout 600  hyperframes_generate(...)   -> exit 124 (timeout)
timeout  90  hyperframes_generate(...)   -> CLI timeout, then fallback succeeded
```

`_run_cli` in `hevi/providers/hyperframes/provider.py` *does* wrap the subprocess in
`asyncio.wait_for` — so this is not an unbounded loop. The default budget is
**`HYPERFRAMES_TIMEOUT_S`, default 600s**, and the CLI does not honour it.

The provider is not broken, though. `hyperframes_generate` catches the CLI failure and
falls back to an ffmpeg path, which **does** produce a real artifact:

```
90s declared budget -> CLI times out -> fallback renders
                     -> h264 1920x1080 4.4s, 20321 bytes
                     -> sha256 6baea9eeafeba9c2e1558f536d66ae96
```

## 3. Timeout contract

`HyperFramesExecutionConfig` — every bound explicit, no `while True`, no bare `sleep()`:

```python
timeout_seconds: int = 180      # must be > 0; unbounded is refused
working_directory: Path
artifact_locator: Path
wall_clock_seconds  = timeout_seconds * 1.5   # harness fires last, never first
```

180s is a *declared* budget passed through the provider's own `config={"timeout_s": …}`
key — the provider's default is not modified, and no timeout was lowered to make a test
pass. The headroom means a provider overrunning its own budget is reported as a provider
failure, not a harness one.

## 4. The adapter

`hevi/qualification/providers/hyperframes.py` returns only
`ExecutionResult(artifact_locator, execution_id, runtime_metadata)`. No checksum, no
duration, no codec, no verdict — there is no field in which to return one.

It records **which mechanism actually produced the artifact**, read from the provider's
own log line rather than guessed:

```
runtime_metadata["render_path"] = "ffmpeg_fallback"   # the truth on this machine
```

Reporting `cli` after the fallback ran would be a false claim about how the artifact came
to exist — which is precisely what this phase exists to prevent.

## 5. Failure matrix

| case | verdict |
|---|---|
| binary missing | `BLOCKED_BY_RUNTIME` |
| provider import fault | `QUALIFICATION_FAILED` |
| **timeout** | **`BLOCKED_BY_RUNTIME`** (`RUNTIME_TIMEOUT`) |
| exit != 0 | `QUALIFICATION_FAILED` |
| no artifact | `REJECTED` |
| digest mismatch | `INVALID_ARTIFACT` |
| valid mp4 | **`QUALIFIED`** |

`BLOCKED_RUNTIME` is a distinct `ExecutionState` from `FAILED`: a timeout means nothing
returned, so nothing can be claimed; an exit-code failure means the runtime answered and
declined. Collapsing them is how a broken provider gets reported as an absent one.

## 6. Verification

```
22 tests · ruff PASS · mypy PASS
real qualification: QUALIFIED, receipt rc-run-hyperframes-…, h264/isom, duration ≥ 1s
mutation: M1-M5 all caught
```

| mutation | result |
|---|---|
| M1 unbounded timeout accepted | caught (3 params) |
| M2 adapter computes a checksum | caught |
| M3 provider regains `hashlib` | caught |
| M4 adapter returns `QUALIFIED` | caught |
| M5 artifact fabricated after a timeout | caught |

## 7. Open

**The CLI hang is not fixed.** It is reported. The fix belongs in
`hevi/providers/hyperframes/provider.py` — most likely the upstream `hyperframes` binary,
not the Python wrapper — and it is outside P9.1.e's permitted scope
(`hevi/providers/hyperframes/`).

Consequences worth carrying: every hyperframes render currently costs the full declared
budget before the fallback runs, so qualification is ~90s per render. A production
pipeline would inherit that latency, and a hang that only ends because a timeout was
declared is a hang.
