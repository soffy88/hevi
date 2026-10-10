import json
import subprocess
from pathlib import Path

from faster_whisper import WhisperModel

PIPER = '/data/soffy/projects/hevi-zero/.venv/bin/piper'
VOICE = '/data/soffy/projects/hevi-zero/voices/zh_CN-huayan-medium.onnx'

def tts_and_align(project_dir: Path, speed=1.2):
    model = WhisperModel("/home/soffy/models/faster-whisper-large-v3-turbo", device="cpu", compute_type="int8")
    
    script_path = project_dir / "scenes" / "script.json"
    if not script_path.exists():
        subprocess.run(["node", str(project_dir / "scenes.js")], cwd=project_dir, check=True)
        
    with open(script_path) as f:
        scenes = json.load(f)
        
    # whiteboard-video uses a separate build dir
    vendor_build_dir = Path("/data/soffy/projects/vendor/trustfuture__simon-skills/skills/whiteboard-video/build")
    project_name = project_dir.name
    audio_dir = vendor_build_dir / project_name / "work" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    
    for sc in scenes:
        full_text = "".join(sc['segments'])
        wav_path = audio_dir / f"{sc['name']}.wav"
        raw_path = audio_dir / f"{sc['name']}.raw.wav"
        
        # TTS
        r = subprocess.run([PIPER, '-m', VOICE, '-f', str(raw_path), '--length_scale', str(1 / speed), '--sentence_silence', '0.25'], input=full_text, text=True, stderr=subprocess.PIPE)
        if r.returncode:
            raise RuntimeError(r.stderr)
        
        subprocess.run(['/home/soffy/.local/bin/ffmpeg', '-y', '-loglevel', 'error', '-i', str(raw_path), '-ar', '48000', '-ac', '2', str(wav_path)], check=True)
        raw_path.unlink()
        
        # ASR (word timestamps)
        segments, _ = model.transcribe(str(wav_path), word_timestamps=True, language="zh")
        words = []
        for segment in segments:
            for word in segment.words:
                words.append({"w": word.word, "s": round(word.start, 3), "e": round(word.end, 3)})
                
        dur_out = subprocess.check_output(['/home/soffy/.local/bin/ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(wav_path)])
        duration = float(dur_out.decode().strip())
        
        def norm(s):
            return "".join(c for c in s if c.isalnum())
        
        acc = 0
        pos_time = []
        for w in words:
            pos_time.append((acc, w['s']))
            acc += len(norm(w['w']))
            
        starts = []
        p = 0
        for seg in sc['segments']:
            starts.append(p)
            p += len(norm(seg))
            
        seg_starts = []
        for sp in starts:
            best = 0
            for cp, t in pos_time:
                if cp <= sp: best = t
                else: break
            seg_starts.append(best)
        seg_starts[0] = 0
        
        json_path = audio_dir / f"{sc['name']}.json"
        with open(json_path, 'w') as f:
            json.dump({
                "name": sc['name'],
                "duration": duration,
                "segmentStarts": seg_starts,
                "segments": sc['segments'],
                "wordList": words
            }, f, ensure_ascii=False, indent=1)
