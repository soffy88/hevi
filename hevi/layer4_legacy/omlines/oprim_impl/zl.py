"""hevi-zero: zero-cost, CPU-only video production primitives.
No GPU, no paid API. Sources: Pexels free API (key already in hevi .env),
NASA/Wikimedia public-domain seeds, piper local TTS, procedural PIL graphics.
"""
from __future__ import annotations
import hashlib, json, math, os, random, subprocess, urllib.parse, urllib.request, wave
import numpy as np

FF = '/home/soffy/.local/bin/ffmpeg'
FP = '/home/soffy/.local/bin/ffprobe'
ROOT = '/data/soffy/projects/hevi-zero'
CACHE = f'{ROOT}/cache'
VOICES = f'{ROOT}/voices'
PIPER = f'{ROOT}/.venv/bin/piper'
FONT = 'Noto Sans CJK SC'
FONT_PATH = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
os.makedirs(CACHE, exist_ok=True)


def sh(cmd: list[str], capture: bool = False):
    """Run ``cmd``.  With ``capture`` return stdout as bytes instead of discarding it."""
    r = subprocess.run(cmd, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                       stderr=subprocess.PIPE, text=not capture)
    if r.returncode:
        err = r.stderr if isinstance(r.stderr, str) else r.stderr.decode('utf-8', 'replace')
        raise RuntimeError(f"cmd failed: {' '.join(cmd)[:300]}\n{err[-1500:]}")
    return r.stdout if capture else None


def dur(p: str) -> float:
    return float(subprocess.check_output([FP, '-v', 'error', '-show_entries', 'format=duration',
                                          '-of', 'csv=p=0', p], text=True).strip())


def sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


# ---------------- TTS (piper, local CPU) ----------------
VOICE = {'zh': 'zh_CN-huayan-medium.onnx', 'en': 'en_US-ryan-medium.onnx'}


def tts(text: str, out: str, lang: str = 'zh', speed: float = 1.0) -> float:
    raw = out + '.raw.wav'
    r = subprocess.run([PIPER, '-m', f'{VOICES}/{VOICE[lang]}', '-f', raw, '--length_scale', str(1 / speed),
                        '--sentence_silence', '0.25'], input=text, text=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    sh([FF, '-y', '-i', raw, '-af', 'highpass=f=70,loudnorm=I=-16:TP=-1.5', '-ar', '44100', '-ac', '2', out])
    os.remove(raw)
    return dur(out)


def tts_lines(lines: list[str], outdir: str, lang: str = 'zh', gap: float = 0.35, speed: float = 1.0):
    """Synthesise each line; return (concat_wav, [(start,end,text)])."""
    os.makedirs(outdir, exist_ok=True)
    parts, cues, t = [], [], 0.0
    sil = f'{outdir}/sil.wav'
    sh([FF, '-y', '-f', 'lavfi', '-i', f'anullsrc=r=44100:cl=stereo', '-t', str(gap), sil])
    for i, line in enumerate(lines):
        p = f'{outdir}/vo_{i:02d}.wav'
        d = tts(line, p, lang, speed)
        cues.append((t, t + d, line))
        parts += [p, sil]
        t += d + gap
    lst = f'{outdir}/vo.txt'
    with open(lst, 'w') as f:
        f.writelines(f"file '{os.path.abspath(p)}'\n" for p in parts)
    out = f'{outdir}/vo.wav'
    sh([FF, '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', out])
    return out, cues


# ---------------- procedural BGM (own, licence-free) ----------------
def bgm(out: str, seconds: float, mood: str = 'warm', sr: int = 44100) -> str:
    rng = np.random.default_rng(7)
    t = np.arange(int(seconds * sr)) / sr
    prog_dict = {'warm': [(220, 277.2, 329.6), (196, 246.9, 293.7), (174.6, 220, 261.6), (196, 246.9, 329.6)],
                 'tense': [(110, 130.8, 164.8), (103.8, 130.8, 155.6), (98, 123.5, 146.8), (103.8, 123.5, 155.6)],
                 'bright': [(261.6, 329.6, 392), (293.7, 349.2, 440), (220, 261.6, 329.6), (246.9, 311.1, 392)],
                 'epic': [(146.8, 174.6, 220), (130.8, 164.8, 196), (110, 130.8, 164.8), (146.8, 174.6, 220)]}
    prog = prog_dict.get(mood, prog_dict['warm'])
    seg = 4.0
    y = np.zeros_like(t)
    for k, chord in enumerate(prog * int(seconds // (seg * 4) + 1)):
        a, b = k * seg, (k + 1) * seg + 1.0
        m = (t >= a) & (t < b)
        if not m.any():
            continue
        tt = t[m] - a
        env = np.minimum(1, tt / 1.2) * np.minimum(1, np.maximum(0, (b - a - tt) / 1.2))
        for f in chord:
            y[m] += env * (np.sin(2 * np.pi * f * tt) * 0.5 + np.sin(2 * np.pi * f * 2.003 * tt) * 0.12)
    if mood == 'bright':
        beat = (np.sin(2 * np.pi * 2 * t) > 0.97).astype(float)
        y += np.convolve(beat, np.exp(-np.arange(2000) / 300), 'same') * rng.normal(0, 0.3, len(t))
    y += rng.normal(0, 0.004, len(t))
    y = y / (np.abs(y).max() + 1e-9) * 0.5
    fade = np.minimum(1, np.minimum(t / 2, (seconds - t) / 2))
    y = (y * fade * 32767).astype(np.int16)
    st = np.stack([y, y], 1)
    with wave.open(out, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes(st.tobytes())
    return out


def mix(vo: str | None, music: str | None, out: str, total: float, music_db: float = -20) -> str:
    """VO over music with sidechain ducking; padded/trimmed to total."""
    if vo and music:
        fc = (f'[1:a]volume={music_db}dB,atrim=0:{total}[m];[0:a]apad,atrim=0:{total},asplit[v][sc];'
              f'[m][sc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[d];'
              f'[v][d]amix=inputs=2:duration=longest:normalize=0,atrim=0:{total}[a]')
        sh([FF, '-y', '-i', vo, '-i', music, '-filter_complex', fc, '-map', '[a]', '-ar', '44100', out])
    else:
        src = vo or music
        sh([FF, '-y', '-i', src, '-af', f'apad,atrim=0:{total}', '-ar', '44100', out])
    return out


# ---------------- Pexels free stock ----------------
def _pexels_key() -> str:
    for line in open('/data/soffy/projects/hevi/.env'):
        if line.startswith('PEXELS_API_KEY='):
            return line.split('=', 1)[1].strip()
    raise RuntimeError('PEXELS_API_KEY missing')


_QUERY_EN_CACHE: dict[str, str] = {}


def query_en(query: str) -> str:
    """Pexels indexes English tags: translate a CJK search phrase with a free translator.

    Falls back to the original phrase when no translator answers (the search then
    simply runs on the Chinese text, as before).
    """
    if not any('\u4e00' <= c <= '\u9fff' for c in query):
        return query
    if query in _QUERY_EN_CACHE:
        return _QUERY_EN_CACHE[query]
    out = query
    try:
        import deep_translator as dt
        for tr in (lambda: dt.GoogleTranslator(source='zh-CN', target='en').translate(query),
                   lambda: dt.MyMemoryTranslator(source='zh-CN', target='en-US').translate(query)):
            try:
                r = (tr() or '').strip()
                if r and not any('\u4e00' <= c <= '\u9fff' for c in r):
                    out = r
                    break
            except Exception:
                continue
    except Exception:
        pass
    _QUERY_EN_CACHE[query] = out
    return out


def pexels(query: str, orientation: str = 'landscape', min_d: float = 5, pick: int = 0) -> dict:
    """Download one Pexels clip (free licence). Returns provenance dict incl. local path."""
    query_cn = query
    query = query_en(query)
    q = urllib.parse.quote(query)
    req = urllib.request.Request(
        f'https://api.pexels.com/videos/search?query={q}&per_page=15&orientation={orientation}',
        headers={'Authorization': _pexels_key(), 'User-Agent': 'hevi-zero'})
    data = json.load(urllib.request.urlopen(req, timeout=20))
    vids = [v for v in data.get('videos', []) if v['duration'] >= min_d]
    if not vids:
        raise RuntimeError(f'pexels: nothing for {query!r}')
    v = vids[min(pick, len(vids) - 1)]
    key = 'width' if orientation == 'landscape' else 'height'
    files = [f for f in v['video_files'] if f.get(key) and 1000 <= f[key] <= 2000 and f['file_type'] == 'video/mp4']
    files = files or sorted(v['video_files'], key=lambda f: -(f.get(key) or 0))
    f = files[0]
    path = f'{CACHE}/pexels_{v["id"]}_{f.get("width")}x{f.get("height")}.mp4'
    if not os.path.exists(path):
        req = urllib.request.Request(f['link'], headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=120) as r, open(path + '.part', 'wb') as o:
            o.write(r.read())
        os.rename(path + '.part', path)
    return {'source': 'pexels', 'query': query, 'query_input': query_cn, 'pexels_id': v['id'], 'page': v['url'],
            'author': v.get('user', {}).get('name'), 'licence': 'Pexels License (free)', 'path': path,
            'duration': v['duration']}


# ---------------- shots / assembly ----------------
def shot(src: str, out: str, d: float, W: int, H: int, ss: float | None = None, move: str = 'push',
         grade: str = '', fps: int = 30) -> str:
    """Trim, scale-cover and add a slow camera move (push/pull/pan) using crop expressions."""
    sd = dur(src)
    if ss is None:
        ss = max(0.0, (sd - d) / 3)
    ss = min(ss, max(0.0, sd - d - 0.05))
    z = 1.12
    sw, sh_ = int(W * z) // 2 * 2, int(H * z) // 2 * 2
    if move in ('push', 'pull'):
        k = f"(1+0.12*t/{d})" if move == 'push' else f"(1.12-0.12*t/{d})"
        crop = (f"scale=w='trunc({W}*{k}/2)*2':h='trunc({H}*{k}/2)*2':eval=frame,"
                f"crop={W}:{H}:x='(iw-{W})/2':y='(ih-{H})/2'")
        vf0 = f"fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
    elif move == 'pan_l':
        crop = f"crop={W}:{H}:x='(iw-{W})*(1-t/{d})':y='(ih-{H})/2'"
    else:  # pan_r
        crop = f"crop={W}:{H}:x='(iw-{W})*t/{d}':y='(ih-{H})/2'"
    if move not in ('push', 'pull'):
        vf0 = f"fps={fps},scale={sw}:{sh_}:force_original_aspect_ratio=increase,crop={sw}:{sh_},"
    vf = (f"{vf0}{crop},"
          f"setsar=1{(',' + grade) if grade else ''},format=yuv420p")
    loop = ['-stream_loop', '-1'] if sd < d + ss else []
    sh([FF, '-y', *loop, '-ss', f'{ss:.2f}', '-t', f'{d:.3f}', '-i', src, '-vf', vf, '-an',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-r', str(fps), out])
    return out


def xfade_concat(shots: list[str], out: str, xd: float = 0.5, trans: str = 'fade') -> str:
    if len(shots) == 1:
        sh([FF, '-y', '-i', shots[0], '-c', 'copy', out]); return out
    ins, fc, prev, off = [], [], '[0:v]', 0.0
    for p in shots:
        ins += ['-i', p]
    for i in range(1, len(shots)):
        off += dur(shots[i - 1]) - xd
        lab = f'[x{i}]'
        fc.append(f'{prev}[{i}:v]xfade=transition={trans}:duration={xd}:offset={off:.3f}{lab}')
        prev = lab
    sh([FF, '-y', *ins, '-filter_complex', ';'.join(fc), '-map', prev, '-c:v', 'libx264', '-preset',
        'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', out])
    return out


def ass_time(s: float) -> str:
    s = max(0, s)
    return f'{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}'


def write_ass(path: str, W: int, H: int, events: list[tuple], styles: dict | None = None) -> str:
    """events: (start, end, style, text_with_override_tags)."""
    base = {
        'Cap': f'{FONT},{int(H * 0.058)},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,{int(H * 0.06)},1',
        'Title': f'{FONT},{int(H * 0.09)},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,2,0,1,4,2,5,60,60,60,1',
        'Kicker': f'{FONT},{int(H * 0.035)},&H0000C8FF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,4,0,1,2,0,5,60,60,60,1',
        'Lower': f'{FONT},{int(H * 0.05)},&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,14,0,1,70,70,{int(H * 0.1)},1',
    }
    base.update(styles or {})
    head = (f'[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n\n'
            '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, '
            'BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, '
            'Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n')
    head += ''.join(f'Style: {k},{v}\n' for k, v in base.items())
    head += '\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    body = ''.join(f'Dialogue: 0,{ass_time(a)},{ass_time(b)},{st},,0,0,0,,{tx}\n' for a, b, st, tx in events)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(head + body)
    return path


def finish(video: str, audio: str | None, out: str, ass: str | None = None, extra_vf: str = '') -> str:
    vf = []
    if extra_vf:
        vf.append(extra_vf)
    if ass:
        vf.append(f"subtitles='{ass}':fontsdir=/usr/share/fonts/opentype/noto")
    args = [FF, '-y', '-i', video]
    if audio:
        args += ['-i', audio]
    args += ['-vf', ','.join(vf) or 'null', '-map', '0:v']
    if audio:
        args += ['-map', '1:a', '-c:a', 'aac', '-b:a', '160k', '-shortest']
    args += ['-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out]
    sh(args)
    return out


def frames_to_video(frame_iter, out: str, W: int, H: int, fps: int = 24) -> str:
    p = subprocess.Popen([FF, '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(fps),
                          '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt',
                          'yuv420p', out], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for fr in frame_iter:
        p.stdin.write(fr.tobytes())
    p.stdin.close(); p.wait()
    if p.returncode:
        raise RuntimeError('frames_to_video failed')
    return out


def rms_envelope(wav: str, fps: int) -> np.ndarray:
    raw = subprocess.check_output([FF, '-v', 'error', '-i', wav, '-ac', '1', '-ar', '16000', '-f', 's16le', '-'])
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    hop = 16000 // fps
    n = len(a) // hop
    e = np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(1))
    return e / (np.percentile(e, 95) + 1e-6)


# ---------------- automated QA (measured, not asserted) ----------------
def qa(path: str, expect_audio: bool = True, min_motion: float = 1.0) -> dict:
    info = json.loads(subprocess.check_output([FP, '-v', 'error', '-show_entries',
                                               'format=duration:stream=codec_type,width,height', '-of', 'json', path]))
    d = float(info['format']['duration'])
    streams = [s['codec_type'] for s in info['streams']]
    v = next(s for s in info['streams'] if s['codec_type'] == 'video')
    raw = subprocess.check_output([FF, '-v', 'error', '-i', path, '-vf', 'fps=4,scale=96:54,format=gray',
                                   '-f', 'rawvideo', '-'])
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 54, 96).astype(np.float32)
    diffs = np.abs(np.diff(fr, axis=0)).mean((1, 2)) if len(fr) > 1 else np.array([0.0])
    static_ratio = float((diffs < 0.6).mean())
    black_ratio = float((fr.mean((1, 2)) < 12).mean())
    text_only = float(((fr < 40).mean((1, 2)) > 0.85).mean())  # mostly-dark frames ~ text cards
    vol = None
    if 'audio' in streams:
        out = subprocess.run([FF, '-i', path, '-af', 'volumedetect', '-vn', '-f', 'null', '-'],
                             stderr=subprocess.PIPE, text=True).stderr
        for l in out.splitlines():
            if 'mean_volume' in l:
                vol = float(l.split(':')[1].split()[0])
    motion_ratio = float((diffs >= 0.6).mean())
    checks = {
        'decodes': True,
        'has_audio': ('audio' in streams) if expect_audio else True,
        'audio_not_silent': (vol is not None and vol > -45) if expect_audio else True,
        'motion_mean_ge_min': float(diffs.mean()) >= min_motion,
        'motion_ratio': round(motion_ratio, 3),
        'static_ratio_lt_0.5': static_ratio < 0.5,
        'black_ratio_lt_0.1': black_ratio < 0.1,
        'dark_textcard_ratio_lt_0.5': text_only < 0.5,
    }
    return {'path': path, 'sha256': sha(path), 'duration': round(d, 3), 'resolution': f"{v['width']}x{v['height']}",
            'streams': streams, 'mean_volume_db': vol, 'motion_mean': round(float(diffs.mean()), 2),
            'motion_ratio': round(motion_ratio, 3),
            'static_ratio': round(static_ratio, 3), 'black_ratio': round(black_ratio, 3),
            'dark_textcard_ratio': round(text_only, 3), 'checks': checks, 'pass': all(checks.values())}


def contact_sheet(path: str, out: str, n: int = 6) -> str:
    d = dur(path)
    tmp = out + '_f'
    os.makedirs(tmp, exist_ok=True)
    for i in range(n):
        sh([FF, '-y', '-ss', f'{d * (i + 0.5) / n:.2f}', '-i', path, '-frames:v', '1', '-vf',
            'scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2', f'{tmp}/{i}.jpg'])
    sh([FF, '-y', '-i', f'{tmp}/%d.jpg', '-vf', 'tile=3x2', '-frames:v', '1', out])
    return out
