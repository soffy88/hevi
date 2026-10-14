# Hevi Webkit ToolKit Map (20 Tools across 7 Layers)

| Layer | Tool Name | Hevi Status / File Location | CPU Headless Render? | License | Conclusion & Rationale |
|---|---|---|---|---|---|
| **1. Agent Skills** | Remotion Skills | `docs/rules/web_animation.md` | Yes | MIT | **Integrated**: Remotion animation patterns for React/headless rendering. |
| **1. Agent Skills** | GSAP Skills | `docs/rules/web_animation.md` | Yes | MIT (Standard) | **Integrated**: GSAP timeline and tween rules for deterministic seek-safe motion. |
| **1. Agent Skills** | Motion AI Kit | `docs/rules/web_animation.md` | Yes | MIT | **Integrated**: Procedural motion design principles and choreography patterns. |
| **1. Agent Skills** | Prompt Templates | `hevi/prompt/` | Yes | MIT | **Existing**: Structured prompt templates for agent generation. |
| **2. Animation** | Remotion | `hevi/talkcraft/` | Yes | MIT / Custom | **Existing**: React-based video composition and rendering framework. |
| **2. Animation** | GSAP | `hevi/creative/` | Yes | Standard / MIT | **Existing**: High-performance JS animation engine. |
| **2. Animation** | Anime.js | `hevi/webrender/` | Yes | MIT | **Integrated**: Lightweight DOM/SVG animation engine for webrender charts and effects. |
| **2. Animation** | Motion Canvas | `hevi/webrender/` | Evaluated (DOM-based export) | MIT | **Integrated (via Anime.js fallback)**: Motion Canvas standalone CLI requires Electron; evaluated for headless export and implemented equivalent chart rendering via Anime.js in webrender. |
| **3. 3D** | Three.js | `hevi/cinematic/` | Yes (headless WebGL via SwiftShader) | MIT | **Existing**: 3D scene rendering, planet orbits, and spatial effects. |
| **3. 3D** | TypeGPU | Not integrated | Yes | MIT | **Unnecessary**: Three.js + SwiftShader satisfies Hevi's headless GPU/CPU 3D requirements. |
| **4. Media** | FFmpeg | `hevi/audio/`, `hevi/video/` | Yes | LGPL / GPL | **Existing**: Core video/audio muxing, encoding, and filtering engine. |
| **4. Media** | Playwright / Chromium | `hevi/webrender/` | Yes | Apache 2.0 | **Integrated**: Headless browser rendering engine with SwiftShader for deterministic frame capture. |
| **4. Media** | SwiftShader | System / Chromium | Yes | Apache 2.0 | **Integrated**: CPU-only software rasterizer for headless WebGL/Canvas rendering. |
| **5. Audio** | Howler.js | Not integrated | No (Browser audio) | MIT | **Unnecessary**: Designed for interactive browser audio playback, not offline rendering. |
| **5. Audio** | Mediabunny | Not integrated | No (Browser audio) | MIT | **Unnecessary**: Browser-side media utility, irrelevant for offline Python rendering pipeline. |
| **5. Audio** | CosyVoice | `hevi/dub/`, `hevi/providers/` | Yes (CPU/GPU) | Apache 2.0 | **Existing**: Neural text-to-speech engine for voiceover generation. |
| **5. Audio** | sfxbad | `hevi/audio_library/` | Yes | MIT | **Existing**: Sound effects library for audio bedding and ducking. |
| **6. Export** | Satori | `hevi/webrender/` | Yes | MIT | **Integrated**: JSX-to-SVG generation without a browser, powering title and subtitle cards. |
| **6. Export** | Resvg | `hevi/webrender/` | Yes | MPL 2.0 | **Integrated**: High-performance SVG-to-PNG rasterizer used alongside Satori. |
| **7. Review** | SVGO | `hevi/webrender/` | Yes | MIT | **Integrated**: SVG optimization and cleaning utility for vector assets before animation. |
