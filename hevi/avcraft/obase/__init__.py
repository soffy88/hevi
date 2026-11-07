"""Layer1 obase：外部运行时适配（ffmpeg / faster-whisper / Ollama），无业务语义。"""

from hevi.avcraft.obase.asr_runtime import transcribe_words
from hevi.avcraft.obase.llm_local import ollama_generate
from hevi.avcraft.obase.media import (
    burn_subtitles,
    ffmpeg_bin,
    ffprobe_bin,
    has_video,
    list_streams,
    mux_soft_subs,
    parse_visual_detect,
    probe_duration,
    render_keep_ranges,
    run_silencedetect,
    run_visual_detect,
)
from hevi.avcraft.obase.motion_catalog import motion_catalog_load, motion_element_code, motion_get
from hevi.avcraft.obase.shot_table import SHOT_SCHEMA, load_shot_table, validate_shot_table
# vision 依赖 cv2/numpy（.venv 已装），惰性：from hevi.avcraft.obase.vision import analyze_frames, audio_energy
# text_layer 依赖 Pillow，惰性：from hevi.avcraft.obase.text_layer import render_text_png
