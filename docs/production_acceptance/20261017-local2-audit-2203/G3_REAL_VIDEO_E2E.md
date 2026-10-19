# G3 — Non-AI video production evidence

## Existing historical artifact (not regenerated during this audit)
- Run directory: `artifacts/real_video/20261005T155226Z`.
- Final MP4: `artifacts/real_video/20261005T155226Z/final/FINAL.mp4`.
- SHA-256: `094235fda18a5b70d34235445c0e48b5d9b027d5a6ddfeedadfc9f715d68a6cd`.
- File size: 7,312,758 bytes.
- Independent `ffprobe`: MP4 container; H.264 video 1280x720 at 25 fps, video stream duration 36.606953 s; AAC audio duration 36.693424 s; overall duration 36.693424 s. Audio/video stream duration difference is approximately 86.5 ms.
- Existing source provenance records NASA public-domain media. The run directory contains a subtitle SRT (17 cues reported by the historical RUN_SUMMARY) and an execution receipt.
- Historical `RUN_SUMMARY.json` reports `duration_s=22.646984`, which conflicts with the actual final file duration of 36.693424 s. Current producer source writes `final_duration_s` and scene durations separately; this appears to be legacy evidence/schema drift. Regenerate the artifact with the current producer and standardize the schema before treating the old summary as release evidence.
- Historical `RUN_SUMMARY.json` says `human_review=PENDING`; machine acceptance is not equivalent to editorial acceptance.
- The final MP4 has video and audio streams, but this audit did not establish whether subtitles are visibly burned into the image or validate subtitle readability across frames.

Decision: PARTIAL. A historical non-AI output exists and is technically playable, but current-code reproduction, subtitle visual QC, summary/probe consistency, and human review remain open.
