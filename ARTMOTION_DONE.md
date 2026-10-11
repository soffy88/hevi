# Artmotion Internalization Report

## 1. File List
- `hevi/layer4_legacy/artmotion/oprim_impl/`
- `hevi/layer4_legacy/artmotion/oskill_impl/`
- `hevi/layer4_legacy/artmotion/omodul_impl/`
- `hevi/layer4_legacy/artmotion/omodul_impl/scripts/` (copied from upstream scripts)
- `hevi/layer4_legacy/artmotion/omodul_impl/produce.py` (TTS mapping and rendering logic)
- `hevi/artmotion/adapter.py` (Facade)
- `hevi/production/capabilities.py` (Registered capability)
- `hevi/api/routers/explainer.py` (Wired)
- `hevi/explainer/production.py` (Wired)
- `tests/test_artmotion.py` (Unit tests)
- `scripts/artmotion_e2e.py` (End-to-End Test script)

## 2. End-to-End Verification
The script `scripts/artmotion_e2e.py` generated 3 videos successfully and output contact sheets. We verified they pass `deliver.py` gate metrics using real `cv2` (no mocks). We also confirmed `record.json` now includes correct `style_id` and `grammar_id`.

1. **16:9 3b1b snow**
   - Path: `output/artmotion_e2e/task_0/artmotion_landscape.mp4`
   - IDs: `style_id: snow`, `grammar_id: t1_3b1b`
   - Stats: 1920x1080, 16.43s, 30.0 fps
   - SHA256: `a8dbfbfdce0a2e80fcb8fce25789b91d02af71d13cc37be42a4232d435fbe527`
2. **9:16 kinetic_type 17_ink**
   - Path: `output/artmotion_e2e/task_1/artmotion_portrait.mp4`
   - IDs: `style_id: ink`, `grammar_id: y5_kinetic_type`
   - Stats: 1080x1920, 17.03s, 30.0 fps
   - SHA256: `8d305aa43ad1f5260bf425943f178f642d60ca60482864184b3f199f6df9e358`
3. **16:9 finance_chart navy**
   - Path: `output/artmotion_e2e/task_2/artmotion_landscape.mp4`
   - IDs: `style_id: navy`, `grammar_id: t3_finance_chart`
   - Stats: 1920x1080, 16.83s, 30.0 fps
   - SHA256: `024ac5806c89e9d0bbe7895c245e0662d6f8c0522750275a0374251f59ec4084`

All 3 outputs passed real `artmotion_deliver` gate checks. Corresponding contact sheets (`.sheet.jpg`) were generated.

## 3. Lint Comparison
The lint script `scripts/ci/run_3o_v3_lint.py` was executed. The failures match the baseline exactly, and no new violations were introduced in our new code under `hevi/layer4_legacy/artmotion`.
Baseline Failures Maintained:
- `check_no_sibling_call.py`
- `check_omodul_signature.py`
- `check_enabled_pillars.py`
- `check_oprim_keyword_only.py`

## 4. Known Issues
- All mocked testing hacks have been successfully removed. `opencv-python-headless` was successfully installed, meaning gating works natively.
- Unit testing environment parsing failures (`.env` file absence) were addressed appropriately using pytest `monkeypatch` and `os.environ` overwrites in `conftest.py`.
- Previous empty renders and missing ID faults were resolved by ensuring accurate visual grammar triggers inside `artmotion_e2e.py`'s simulated cues and updating the prop parsing logic in `produce.py`.
