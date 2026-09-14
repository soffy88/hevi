# InkOS clean-room boundary

InkOS was audited only as a public capability reference. The audit workspace
is external to HEVI and is not a runtime dependency. HEVI contracts are
implemented under the existing `obase`, `oprim`, `oskill`, `omodul`, and
`oservi` responsibilities.

Recorded upstream metadata:

- repository: `https://github.com/Narcooo/inkos`
- branch: `master`
- audited commit: `091048383f411eb99948a8764f42b6fd13006f9b`
- observed license: `AGPL-3.0-only`
- observed package version: `1.8.0`

The HEVI branch contains no InkOS source, prompt, skill text, tests, fixtures,
templates, CSS, or runtime package. Public behavior was paraphrased into the
capability ledger; implementation decisions and contracts are HEVI-native.
