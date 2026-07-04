# BGM 素材放这里

导演台/管线按**情绪**选曲。放法:

```
assets/audio/bgm/<mood>/<any>.mp3
```

已支持的情绪(与前端下拉一致):`warm` 温暖 · `upbeat` 轻快 · `tense` 紧张 · `epic` 史诗 · `mystery` 悬疑。
每个情绪目录放 1+ 支音频,`BGMLibrary.select_bgm(mood)` 取排序后第一支(确定性)。

装配器(`assemble_longvideo`)会把 BGM 压于旁白之下(sidechain ducking,默认 -18dB)混入成片。
目录空或不存在 → 静默跳过配乐,不报错。也可直接传文件路径代替情绪名。
