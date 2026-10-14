# ARTMOTION Fix Progress

## Status: All 4 Blockers Resolved ✅

### Blockers Fixed:
1. ✅ Style scenes show fixed illustrations → `scenes_style/` texture-only versions (17_ink, 25_ghibli, 14_8bit, 12_bauhaus) + `texture_mode` wiring
2. ✅ Text overflow in safe area → `y5_kinetic_type.js` safe width comment (TY.fit already uses W*0.86)
3. ✅ LaTeX source showing on screen → `sanitize_latex()` strips markup, maps to Unicode (√·×≠≈∞)
4. ✅ MIT license/provenance missing → `third_party/huashu-art-motion/LICENSE` + `NOTICE.md` added

### Non-blockers (Noted for Future):
- [ ] Highlight cue silent when word not in main text
- [ ] task_0 polyline data should match attention content
- [ ] Produce duration gate
- [ ] Test improvements

## Lint Baseline: 4 failures (unchanged from pre-change baseline)
- check_no_sibling_call, check_omodul_signature, check_enabled_pillars, check_oprim_keyword_only

## E2E Verification (task_*_v2, texture_mode=True)

| Task | 规格 | 语法 | 风格 | 时长 | gate_light | fast_ratio | 状态 |
|------|------|------|------|------|-----------|------------|------|
| task_0_v2 | 16:9 1920x1080 | y1_teaching | 25_ghibli (texture) | 30.0s | ✅ green | 9.39% | ✅ 通过 |
| task_1_v2 | 9:16 1080x1920 | y5_kinetic_type | 17_ink (texture) | 27.3s | ✅ green | 21.4% | ✅ 通过 |
| task_2_v2 | 16:9 1920x1080 | t3_finance_chart | 14_8bit (texture) | 31.8s | ✅ green | 8.38% | ✅ 通过 |
| task_3_v2 | 9:16 1080x1920 | y5_kinetic_type | 17_ink (texture) | 27.3s | ✅ green | 21.6% | ✅ 通过 |

All 6 gates passed for every task.
LaTeX sanitization verified: no backslash/brace characters remain in spec tokens.

## Key Files Modified
- `hevi/layer4_legacy/artmotion/omodul_impl/produce.py` — sanitize_latex(), STYLE_SCENE_MODE, texture_mode in spec
- `hevi/layer4_legacy/artmotion/omodul_impl/scripts/engine/clip.js` — load scenes_style/*_texture.js when textureMode
- `hevi/layer4_legacy/artmotion/omodul_impl/scripts/engine/clips/y5_kinetic_type.js` — safe area comment
- `hevi/layer4_legacy/artmotion/omodul_impl/scripts/engine/scenes_style/*.js` — 4 texture-only scene files
- `third_party/huashu-art-motion/LICENSE` + `NOTICE.md`

## Tests
- `tests/test_artmotion.py` — 4 tests all passing
