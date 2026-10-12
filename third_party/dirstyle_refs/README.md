# dirstyle 参考仓库

上游仓库均已放到本目录，仅用于开发参考（非商用），保留上游署名与许可证。

| 目录 | 上游 | commit | 许可证 | 吸收范围 |
|---|---|---|---|---|
| `mikefluff_skills/style-library-video/` | github.com/Mikefluff/skills | 24bbcc2 | MIT | **12 种导演风格**（chazelle/lynch/edgar-wright/fincher/inarritu/nolan/refn/soderbergh/tarkovsky/villeneuve/wes-anderson/wong-kar-wai），每种有 lens/lighting/palette/motion/editing rhythm/shot anchor/action vocabulary/best for/avoid for。与 10 位重叠的 4 位（王家卫/诺兰/韦斯/芬奇）合并补充字段；其余 8 位作为新增风格吸收（共 ≥18 种）。 |
| `nolanx/` | github.com/nolanx-ai/nolanx.ai | 595d863 | MIT | 方法论 skill（director-visual-language、cinema-studio-lens-look、shot-size-and-angle-language、storyboard-shot-design、lighting-continuity-design、sd2-pe、short-drama-hook-engineering）：吸收**镜头尺寸/角度/运镜词表**和"抽象词→具体决策"规则，用于编译器的运镜库和虚词黑名单。 |
| `awesome_seedance/` | github.com/ZeroLu/awesome-seedance | ea0d373 | MIT | Seedance 2.0 实战提示词（含王家卫雨夜电话亭、Villeneuve、竖屏霸总短剧、短剧雨夜）：参考**时间码分段写法**和竖屏短剧写法；可作为编译器输出样例/测试对照。 |
| `ai_shortfilm_prompts/` | github.com/jnMetaCode/ai-shortfilm-prompts | 5e7c374 | MIT（仅 [A] 部分） | **只吸收 MIT [A] 部分**（templates/、methodology、cheatsheet）：21+ 套类型模板（micro-drama、found-footage-horror、fashion-film、food-asmr、cyberpunk-city、genre-camera-sop、camera-move-library、atmosphere-prefabs…）→ 作为"题材模板（genre）"层，与导演风格正交组合。**不得复制 prompts/ 下 Mx-Shell [B] All-Rights-Reserved 内容**（本次已未拷贝）。 |

## 许可证

全部上游均为 MIT（ai_shortfilm_prompts 为混合许可，仅吸收 MIT [A] 部分）。
许可证文件见各子目录 `LICENSE`。

## 使用方式

`hevi/layer4_legacy/dirstyle/data/*.json` 中的风格条目 `source.absorbed_from`
字段记录了每条风格来自哪个上游。
