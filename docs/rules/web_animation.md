# Hevi Web Animation Rules (Webkit R1)

This rule card establishes mandatory development standards for Hevi AI workers writing web animation code (Remotion, GSAP, Anime.js, and headless browser workflows).

## 1. Timeline & Seemless Execution
- **Pause Before Seek**: Always ensure the animation timeline or player is paused (`timeline.pause()`, `gsap.globalTimeline.pause()`) before executing any programmatic seek (`seek(t)` or `goToAndStop(frame)`).
- **No Real-time rAF**: Never rely on `requestAnimationFrame` for offline deterministic rendering. All time values must be explicitly driven by elapsed seconds $t$ or frame index $f$ relative to start time.
- **Deterministic Seed**: Random number generators or procedural noise functions must accept a fixed seed when deterministic reproducibility is required.

## 2. React & DOM Lifecycle
- **Cleanup on Unmount**: All GSAP timelines, ResizeObservers, IntersectionObservers, and canvas render loops must be explicitly killed/disconnected in React `useEffect` cleanup return functions.
- **No Memory Leaks in Headless Puppeteer**: When rendering HTML via Playwright Chromium, wait for network idle and specific custom completion events (e.g., `window.__animationReady = true`) before capturing frames.

## 3. Typography & Styling
- **Font Availability**: Use standard fallback stacks with system fonts or bundled fonts (`Noto Sans SC`) to prevent tofu boxes (missing glyphs) in Chinese subtitle and title cards.
- **Bounding Box Safety**: Keep text elements within safe margins (at least 64px padding for 16:9, 96px for 9:16) to avoid clipping and overlap during rendering.

## 4. Performance & Resource Bounds
- **GPU Acceleration**: Prefer CSS transforms (`transform: translate3d`, `scale`) over layout-triggering properties (`width`, `height`, `top`, `left`).
- **Asset Optimization**: All SVG assets must be cleaned via SVGO prior to embedding in animation scenes to strip unnecessary metadata and reduce bundle size.
