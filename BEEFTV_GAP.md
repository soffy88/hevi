# BEEFTV Gap & Feasibility Analysis for Hevi

## 1. Overview of BeefTV
BeefTV is a modern, high-performance, AI-native video workspace and desktop application (macOS/Windows) built around a local-first canvas architecture. It features extensive multi-model integration, rich plugin packages, storyboard management, timeline editing, and advanced video generation/delivery pipelines.

## 2. Feature Comparison: BeefTV vs. Hevi
- **Canvas & UI:** BeefTV features a sophisticated Leafer/Canvas based UI, node graph, and timeline. Hevi is primarily an AI talking-head / short video pipeline tool (TALKEDIT, SHOTLANG, HUASHU, remote TTS, faster-whisper).
- **Core Architecture:** BeefTV is a massive TypeScript/Node/Electron/Bun application with numerous custom plugins, React components, and native release pipelines. Hevi is focused on lean modular AI pipelines and local SQLite-backed tasks.
- **License Considerations:** BeefTV uses a source-available license (Part A) which restricts commercial consideration, selling, bundling, and external services of Covered Material without separate written authorization from `lucas@bf-labs.cn`.

## 3. Value Assessment & Decision
- **Value to Hevi:** Low to moderate. BeefTV's architecture is a fully-fledged proprietary desktop app/workspace rather than a small drop-in library or component. Directly porting or copying parts of its commercial-restricted source code could violate licensing terms or bloat Hevi's lightweight pipeline design.
- **Decision:** **Do not integrate BeefTV code into Hevi** due to licensing restrictions on commercial-adjacent use/redistribution (BeefTV Source Available License 1.0) and architectural mismatch (BeefTV is a massive standalone desktop application framework, whereas Hevi is an AI video/audio generation pipeline).

## 4. Conclusion
BeefTV is recorded as an external reference project, but no code from BeefTV is integrated into Hevi.
