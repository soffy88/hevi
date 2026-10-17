# capcut-cli Runtime Bootstrap

> **This document is not authority.** It records how to install a pinned external
> runtime dependency so P5.2's editable-backend tests can execute for real.
> It defines no render authority, no pipeline behaviour, and no gate.
>
> The render authority remains `hevi/editable/base.py` (`EditableProjectBackend`,
> `EditableProjectManifest`). The version contract remains
> `hevi/editable/capcut_cli.py` (`EXPECTED_VERSION` / `EXPECTED_REVISION`).
> Nothing in this file may be used to justify a different version.

---

## What this is

`capcut-cli` is the external binary behind P5.2's `CAPCUT_CLI` editable backend.
P5.2 spec §70 requires it be version-pinned; the pin is declared in code and is
**not** duplicated here as an authority.

| Field | Value |
|-------|-------|
| Durable install root | `/data/soffy/tools/capcut-cli` |
| Binary | `/data/soffy/tools/capcut-cli/node_modules/.bin/capcut-cli` |
| Pinned version | `0.26.0` |
| Upstream | `github.com/renezander030/capcut-cli` (named in P5.2 spec §2) |
| License | MIT |
| Registry tarball | `https://registry.npmjs.org/capcut-cli/-/capcut-cli-0.26.0.tgz` |
| Integrity | `sha512-zt3GVw9Xfrrx/uryq40T8Q4dfg3BEdpyhCMI2C1N7B9zVVBd4otvimPaqQkHw3sQLqQ+1XXRvpsXdID+f02XBQ==` |
| Install strategy | `npm install --ignore-scripts`, isolated prefix, no global mutation |

The install root is on the persistent `ext4` volume at `/data`. It is
deliberately **outside** the git worktree so that provisioning a binary never
dirties the repository.

---

## Why an isolated prefix

`/tmp` is a `tmpfs` (RAM-backed) and does not survive reboot. An earlier probe
install lived under `/tmp/opencode/`; it was moved here for that reason alone.
The prefix is also non-global: nothing was written to system `node_modules`,
so no other project on this shared host is affected.

`--ignore-scripts` is used so that no package lifecycle script executes during
install.

---

## Reinstall / verify

```bash
# verify the pin actually present on disk
/data/soffy/tools/capcut-cli/node_modules/.bin/capcut-cli --version
# expect exactly: 0.26.0

# re-provision from scratch (idempotent)
rm -rf /data/soffy/tools/capcut-cli
mkdir -p /data/soffy/tools/capcut-cli
npm install --prefix /data/soffy/tools/capcut-cli \
            --ignore-scripts --no-audit --no-fund \
            capcut-cli@0.26.0

# confirm resolved tarball + integrity match the table above
python3 -c "import json;d=json.load(open('/data/soffy/tools/capcut-cli/package-lock.json'));\
print(d['packages']['node_modules/capcut-cli'])"
```

If `--version` ever reports anything other than `0.26.0`, the backend reports
itself unavailable. That is the intended fail-closed behaviour — do not edit
`EXPECTED_VERSION` to make it pass.

---

## Pointing HEVI at the binary

`CapCutCliBackend` resolves its binary in this order:

1. an explicit constructor argument, else
2. `$CAPCUT_CLI_BIN`, else
3. `capcut-cli` on `PATH`

So no code change is needed to use the durable install:

```bash
export CAPCUT_CLI_BIN=/data/soffy/tools/capcut-cli/node_modules/.bin/capcut-cli
```

To make it apply to future shells without touching the repository, add to
`~/.bashrc` (a host-level change, deliberately *not* performed here):

```bash
export CAPCUT_CLI_BIN=/data/soffy/tools/capcut-cli/node_modules/.bin/capcut-cli
```

Until that is set, tests that exercise the CapCut backend will report the
backend `UNAVAILABLE` and will skip rather than fabricate a projection.

---

## Effect on qualification

With the binary present and reporting `0.26.0`, P5.2's suite goes from
`305 passed / 2 failed / 23 skipped` to `330 passed / 0 failed / 0 skipped`.
The 23 previously-skipped tests are real E2E assertions that now execute.

This closes an **environment** gap only. It does not alter any gate, does not
change P5.2's qualification verdict, and does not affect P5.1 (still
`BLOCKED_BY_PROVIDER`) or P5.3 (`QUALIFIED_CORE`).
