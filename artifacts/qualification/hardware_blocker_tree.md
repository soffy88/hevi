# Hardware blocker tree

```text
GPU_HARDWARE
├── history_scene
│   └── wan_local (SERVICE_NOT_STARTED / GPU_HARDWARE)
├── explainer
│   └── CosyVoice (SERVICE_NOT_STARTED / GPU_HARDWARE)
├── reference_adapt
│   └── CosyVoice (SERVICE_NOT_STARTED / GPU_HARDWARE)
├── director_pipeline
│   └── h3_local
├── cinematic
│   └── h3_local
├── talking_head
│   └── h3_local
└── avatar_spokesperson
    └── h3_local
```

CosyVoice and wan_local are derived consequences of the same host GPU failure;
the top-level release blocker is counted once.
