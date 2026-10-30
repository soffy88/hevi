# Colab hardware advisor: method attribution

`model.colab_hardware_advisor` (`hevi/capabilities/colab_hardware_advisor.py`)
is a clean-room rewrite of a method only: classify a job, check it
against caller-supplied runtime measurements, block an expensive
first download, warn on an oversized runtime for a small job, and
suggest resident-model tuning on a large-memory runtime.

## Sources consulted (verification report only)

- `workspace/colab-ultra-workstation-check.md` (2026-10-30): a
  read-only verification report. It checked, by GitHub API and
  raw-file reading, without logging in, spending money,
  downloading model weights, or running a paid GPU:
  - `googlecolab/colab-mcp` (Apache-2.0) and
    `googlecolab/google-colab-cli` (Apache-2.0): official
    projects; browser-session bridging and CLI session commands
    were verified from their code.
  - `yuanyang749/colab-ultra-workstation`: a 9-star personal
    repository with **no LICENSE file found**. No wording, code,
    notebook, script, or white-paper text was copied from it.
    Only the method ideas (six task classes, a download guard, an
    oversized-runtime warning, large-memory tuning suggestions)
    were re-expressed in new code, with the rate table and the
    contradictory figures deliberately left out.

## Deliberately excluded

- The third-party drive-mount extension (`deluxebear/colab-dfs-ext`,
  no LICENSE found): its long-lived credential handling (a
  refresh token carried into notebook cells and written to disk
  on the cloud instance) was judged high-risk in the verification
  report and is not used, referenced, or reimplemented here.
- Any content about bypassing safety filtering, and any
  "uncensored" encoder or weight: excluded entirely.
- The GPL-3.0 node collection checked in the same report: only
  the idea of a parameter was noted; no code was taken.
- No Colab API is called, no runtime is switched, and no
  credential is read or stored by this module.

## Standing rules this module follows

- Rates and balances always come from the caller as dated
  runtime snapshots. No price table is baked into the code.
- Memory coefficients are caller-configurable and labelled
  order-of-magnitude references only.
- Switching a paid runtime is a person's decision, made by
  saving the change in the Colab page or by a CLI command the
  account owner explicitly authorises. This module only advises.
