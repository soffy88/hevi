# Distribution provenance and license boundary

## MatrixMedia

- source: `https://github.com/hanliang97/MatrixMedia`
- qualification checkout: external to HEVI, `/data/soffy/qualification/MatrixMedia`
- pinned upstream SHA: `8b6216006005f38dde83018b97847274ee970688`
- version: `0.11.3` (package metadata; checkout describes itself as `v0.11.3-2`)
- license: GPL-2.0-only
- integration: process-level CLI/MCP invocation only
- source copied into HEVI: **NO**

The external qualification checkout is not a HEVI runtime dependency. HEVI
does not link, import, vendor, or copy MatrixMedia code. The provider records
the source artifact SHA, request metadata, provider job reference, account,
platform, and normalized result.

## Platform evidence policy

README claims are not capability evidence. A platform is marked
`SUPPORTED_REAL` only after a real account probe and successful real operation
with an auditable artifact. A missing login is `SUPPORTED_NEEDS_LOGIN`; an
unreachable executable is `NOT_VERIFIED`.

## short-video-factory

This branch uses clean-room regression specifications only. No source code,
fixtures, media, or implementation from that project is copied into HEVI.
`SHORT_VIDEO_FACTORY_CODE_COPIED=NO`.
