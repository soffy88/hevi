# SCENE3D 可选调研：CPU 图生 3D（TripoSR / SF3D）结论

> 本节为 SCENE3D_TASK.md 中"可选调研"项的结论，不接入渲染管线。
> 结论：CPU 端单图生 3D 在本机上不具备"短于 10 分钟"的工程可行性，**不接入**。

## 1. 候选模型

| 模型 | 权重大小 | 输入 | 输出 | 许可证 |
|---|---|---|---|---|
| TripoSR (Stability AI + Tripo) | ~1.4 GB (model.ckpt) | 1 张 RGB | textured mesh (GLB) | MIT |
| SF3D (Stable Fast 3D) | ~3 GB | 1 张 RGB | UV-unwrapped mesh | Stability Community License |

## 2. 在本机上的工程现实

- **环境无 GPU**，只能用 CPU。TripoSR 的官方 demo 报告 GPU 推理 0.5s，
  CPU 推理在 PyTorch eager 模式下通常 5–15 分钟一张（512³ 体素 marching
  cubes + NeRF 风格 MLP）。
- 模型权重分布在 Hugging Face / GitHub releases：Hugging Face 在本机被
  墙，GitHub 直连也不通。ModelScope 上有 `AI-ModelScope/TripoSR` 的
  *空壳*仓库（404），没有真正的权重二进制；同名的 `ms-swift/TripoSR-pipeline`
  也不是 PyTorch 原生权重。
- 即便拉下权重，CPU 端完成一次前向 + marching cubes 也要 10 分钟以上，
  远超过任务里"超过 10 分钟就只写结论，不接入"的阈值。
- 即使单次推理可控，把"图生 3D"接入数据驱动的 JSON 场景会引入不可控
  变量：模型输出几何细节不可预测，无法保证 *小王子* 风格的 toon /
  低面数外观；产生的 mesh 仍需手工减面、UV、贴图才能和现有程序化场景
  共存，反而比"用 CC0 资产 + 程序化生成"工作量大。

## 3. 决定

**不接入**。SCENE3D 的视觉资产全部为程序化生成（`template.py` 内
`makePlanet` / `makeField` / `makeFox` / `makeRock` / `makeTree`），
保证：
- 跨平台一致（CPU only，无模型下载）
- 风格可控（toon / lambert 渐变 + 低面数）
- 零成本、零网络

未来如确实需要图生 3D，建议：
1. 接入远程 GPU 服务（与"不调付费 API"原则冲突），或
2. 走 TripoSG / Hunyuan3D 这类蒸馏小模型，权重 < 500 MB，CPU 可在
   5 分钟内出模。但即便如此，仍需后处理成 toon 风格。

## 4. 备注

- ModelScope `AI-ModelScope/TripoSR` 探活 HTTP 200，但下载链接需要
  modelscope SDK 鉴权（API token），本机无该 token。
- 本结论随 SCENE3D-R1 一起提交；如未来解锁 GPU，可重新评估。
