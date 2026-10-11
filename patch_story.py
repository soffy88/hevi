import re

with open('third_party/lanshu_explainer/tools/story.py', 'r') as f:
    content = f.read()

new_tts = """def tts(text, voice, speed, out_mp3, out_json):
    import subprocess
    import os
    import json
    from faster_whisper import WhisperModel
    PIPER = '/data/soffy/projects/hevi-zero/.venv/bin/piper'
    VOICE_MODEL = '/data/soffy/projects/hevi-zero/voices/zh_CN-huayan-medium.onnx'
    FFMPEG = '/home/soffy/.local/bin/ffmpeg'
    
    raw = out_mp3 + '.raw.wav'
    subprocess.run([PIPER, '-m', VOICE_MODEL, '-f', raw, '--length_scale', str(1 / speed), '--sentence_silence', '0.25'], input=text, text=True, check=True)
    subprocess.run([FFMPEG, '-y', '-loglevel', 'error', '-i', raw, '-af', 'highpass=f=70,loudnorm=I=-16:TP=-1.5', '-ar', '44100', '-ac', '1', out_mp3], check=True)
    os.remove(raw)

    model = WhisperModel('/home/soffy/models/faster-whisper-large-v3-turbo', device='cpu', compute_type='int8')
    segments, _ = model.transcribe(out_mp3, word_timestamps=True, language='zh')
    
    tw = []
    for segment in segments:
        for word in segment.words:
            tw.append({"word_begin": 0, "word_end": 0, "time_begin": int(word.start * 1000), "word": word.word})
    
    # fake minimax format
    subs = [{"timestamped_words": tw, "text_begin": 0}]
    json.dump(subs, open(out_json, 'w', encoding='utf-8'), ensure_ascii=False)
"""

content = re.sub(r'def tts\(.*?\):.*?(?=\n\n\n)', new_tts, content, flags=re.DOTALL)

new_words_from = """def words_from_engine(text, subs, offset):
    tw = []
    for seg in subs:
        for w in seg.get("timestamped_words", []):
            tw.append(w)
            
    # Simple uniform distribution of text characters to timestamped words
    chars = [u for u in UNIT.findall(text) if SPOKEN.match(u)]
    if not chars:
        return []
        
    res = []
    for i, c in enumerate(chars):
        idx = min(len(tw) - 1, int((i / len(chars)) * len(tw)))
        t = tw[idx]["time_begin"] / 1000.0 if tw else 0
        res.append((c, t + offset))
    return res
"""

content = re.sub(r'def words_from_engine\(.*?\):.*?(?=\n\n\n)', new_words_from, content, flags=re.DOTALL)

with open('third_party/lanshu_explainer/tools/story.py', 'w') as f:
    f.write(content)
