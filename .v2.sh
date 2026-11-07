cd /data/soffy/projects/platform/3O
export PYTHONPATH=$PWD/obase-repo3o:$PWD/oprim-repo3o:$PWD/oskill-repo3o:$PWD/omodul-repo3o:$PWD/oservi-repo3o
for d in obase oprim oskill omodul oservi; do w=$d-repo3o; echo "## $w dirty=$(git -C $w status --short | wc -l)"; git -C $w log --oneline -3 | grep -i repo3o
 T=$(cd $w; git diff --name-only bac8770..HEAD 2>/dev/null >/dev/null; git log --name-only --format= --grep=repo3o | grep -E "^tests/.*\.py$" | sort -u)
 [ -n "$T" ] && (cd $w; timeout 300 python3 -m pytest -q -p no:cacheprovider $(ls $T 2>/dev/null) 2>&1 | tail -1); done
python3 -c "
from oprim import crop_video_to_portrait, multimodal_embed, synthesize_speech_chunk, vector_cosine_search, whisper_transcribe; print('oprim import OK')" 2>&1 | tail -1
python3 -c "import oskill; n=['highlight_detection_algorithm','query_expansion','search_synthesize_loop','dialogue_script_generation','multi_speaker_tts_merge','video_subtitle_align','template_scene_compose','multimodal_index_pipeline']; print('oskill', [x for x in n if not hasattr(oskill,x)] or 'all OK', oskill.__file__)" 2>&1 | tail -1
python3 -c "import oprim;print(oprim.__file__)"
