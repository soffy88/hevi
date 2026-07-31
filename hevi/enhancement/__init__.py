"""hevi 图像增强后处理 —— upscale / bg_remove / face_restore / color_grade。

对标 OpenMontage 的 tools/enhancement/(5 个工具)。Hevi 此前无独立增强层,
verdict 发现问题后只能重生成,不能"后期修"。有了增强层,retake-protocol 的
"fix in post"档位就有了实际执行体(比重生成省 10 倍)。

四个工具全部是本地推理(GPU)或 ffmpeg,不走云端 provider:
  - upscale: Real-ESRGAN(4x) / ESRGAN(2x)
  - bg_remove: rembg(U2Net)
  - face_restore: CodeFormer / GFPGAN
  - color_grade: ffmpeg LUTs(确定性,零模型成本)

用法:
    from hevi.enhancement import upscale, remove_background, restore_face, color_grade
    upscale(src_path, out_path, scale=2)
    remove_background(src_path, out_path)
    restore_face(src_path, out_path)
    color_grade(src_path, out_path, lut="warm_cinema")
"""

from hevi.enhancement.bg_remove import remove_background
from hevi.enhancement.color_grade import color_grade, list_luts
from hevi.enhancement.face_restore import restore_face
from hevi.enhancement.upscale import upscale

__all__ = [
    "color_grade",
    "list_luts",
    "remove_background",
    "restore_face",
    "upscale",
]
