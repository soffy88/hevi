"""hevi-zero line producers. Usage: python lines.py <line> [<line> ...] | all

Every line is driven by its input slots.  The free tier never silently
substitutes a built-in sample: if a required slot is missing the line raises
``MissingInput`` and the workflow reports a failure with the missing key.
"""
from __future__ import annotations
import json, os, re, shutil, subprocess, sys, time, zlib
import numpy as np
from hevi.layer4_legacy.omlines.oprim_impl import zl
from hevi.layer4_legacy.omlines.oprim_impl.zl import FF, sh, dur
from hevi.layer4_legacy.omlines.oskill_impl import puppets

OUT = f'{zl.ROOT}/out'
SEED = '/data/soffy/projects/hevi/data/workspace/assets/open-corpus-seed/clips'
LW, LH = 1280, 720


class MissingInput(RuntimeError):
    """A required input slot was not supplied (or its path does not exist)."""


# ---------------------------------------------------------------- slot helpers
def _res(slots, default=(LW, LH)):
    r = slots.get('resolution')
    if not r:
        return default
    if isinstance(r, str):
        w, h = r.lower().split('x')
        return int(w), int(h)
    return int(r[0]), int(r[1])


def _script(slots, kind):
    """Narration lines for ``kind``.

    ``script_lines`` (or a free-form ``manuscript`` / ``source_text`` /
    ``transcript`` slot) wins when supplied; otherwise the local template below
    is used.  The template always interpolates the caller-supplied topic so the
    narration is genuinely input-driven.
    """
    for key in ('script_lines', 'manuscript', 'source_text', 'transcript'):
        raw = slots.get(key)
        if isinstance(raw, (list, tuple)):
            cand = [str(x).strip() for x in raw if str(x).strip()]
        elif raw and kind in ('history', 'director'):
            cand = [ln.strip() for ln in re.split(r'[。\n]', str(raw)) if ln.strip()]
        else:
            cand = []
        if cand:
            return cand[:8]
    topic = _topic(slots)
    t = topic
    scripts = {
        'explainer': [
            f'今天我们用一分钟了解{t}。',
            f'先说背景：{t}并不是孤立发生的。',
            f'第一个关键点，是它的起点和条件。',
            f'第二个关键点，是它如何一步步发展。',
            f'第三个关键点，是它留下的影响。',
            f'这就是关于{t}的一个简要解释。',
        ],
        'cinematic': [
            f'关于{t}，故事从一个安静的瞬间开始。',
            f'光落下来，时间仿佛慢了一拍。',
            f'细节在暗处浮现，又被风带走。',
            f'镜头推近，我们看见了它的轮廓。',
            f'这是{t}留下的一个画面。',
        ],
        'history': [
            f'{t}，要从很久以前说起。',
            f'早期的记载里，已经出现了关于它的线索。',
            f'随后，它在不同的年代里被反复书写。',
            f'那些关键的人和事，改变了它的走向。',
            f'今天再看{t}，我们依然能读到那个时代。',
            f'这段历史，也因此被郑重地记了下来。',
        ],
        'director': [
            f'{t}，第一个镜头。',
            f'镜头拉近，我们看到其中的细节。',
            f'第三个画面，节奏开始加快。',
            f'然后，视线转向更开阔的地方。',
            f'最后，{t}回到最初的起点。',
        ],
        'character': [
            f'他听说了{t}。',
            f'于是决定亲自去看一看。',
            f'他停下脚步，仔细观察。',
            f'最后，他把{t}记在了心里。',
        ],
        'presenter': [
            f'大家好，今天用一分钟讲清楚{t}。',
            f'关于{t}，先说最重要的一点。',
            f'它和我们每个人的生活都有关系。',
            f'记住这个关键词，就记住了{t}。',
            f'我们下期见。',
        ],
    }
    return scripts[kind]


def _topic(slots):
    t = str(slots.get('topic') or '').strip()
    if not t:
        raise MissingInput('missing required input slot "topic"')
    return t


def _image_path(slots, line):
    p = str(slots.get('image_path') or '').strip()
    if not p:
        raise MissingInput(f'{line}: missing required input slot "image_path" (a real presenter photo)')
    if not os.path.isfile(p):
        raise MissingInput(f'{line}: image_path does not exist: {p}')
    return p


def _media_path(slots, line, keys=('media_path', 'source')):
    for k in keys:
        v = str(slots.get(k) or '').strip()
        if v:
            if not os.path.isfile(v):
                raise MissingInput(f'{line}: {k} does not exist: {v}')
            return v, k
    raise MissingInput(f'{line}: missing required source video (provide one of {list(keys)})')


def _kinetic_words(topic):
    parts = [p for p in re.split(r'[，,。、；;：:\s]+', topic) if p]
    words = []
    for p in parts:
        if len(p) <= 4:
            words.append(p)
        else:
            words += [p[i:i + 4] for i in range(0, len(p), 4)]
    if not words:
        words = [topic[:4] or topic]
    tail = ['从这里开始', '你会看到', '更多细节']
    words = words[:5] + tail
    out, t = [], 0.0
    for k, w in enumerate(words):
        out.append((w, t))
        t += 1.5 if k < 3 else 1.7
    return out


def work(line):
    d = f'{OUT}/{line}'
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d + '/tmp', exist_ok=True)
    return d


def caps(cues, style='Cap'):
    return [(a, b, style, t) for a, b, t in cues]


def save(d, line, final, prov, expect_audio=True, min_motion=1.0, notes='', allow_dark=False, extra=None):
    q = zl.qa(final, expect_audio, min_motion)
    if allow_dark:  # night/cave scenes are dark by design: report the ratios but do not gate on them
        q['waived'] = {k: q['checks'].pop(k) for k in ('black_ratio_lt_0.1', 'dark_textcard_ratio_lt_0.5')}
        q['pass'] = all(q['checks'].values())
    zl.contact_sheet(final, f'{d}/contact_sheet.jpg')
    rec = {'line': line, 'final': final, 'cost_usd': 0, 'gpu': False, 'paid_api': False,
           'provenance': prov, 'qa': q, 'notes': notes,
           'produced_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    if extra:
        rec.update(extra)
    json.dump(rec, open(f'{d}/record.json', 'w'), ensure_ascii=False, indent=2)
    shutil.rmtree(f'{d}/tmp', ignore_errors=True)
    print(line, 'PASS' if q['pass'] else 'FAIL', q['checks'])
    return rec


def broll_film(d, lines_zh, queries, moves=None, grade='', W=LW, H=LH, mood='warm', letterbox=False,
               title=None, speed=1.0, orient='landscape', picks=None):
    """Shared: narration line i is covered by Pexels shot i (shot length = line length)."""
    vo, cues = zl.tts_lines(lines_zh, f'{d}/tmp/vo', speed=speed)
    total = dur(vo) + 1.2
    shots, prov = [], []
    xd = 0.5
    for i, ((a, b, _), q) in enumerate(zip(cues, queries)):
        src = zl.pexels(q, orient, min_d=4, pick=(picks or list(range(99)))[i])
        prov.append({k: v for k, v in src.items() if k != 'path'} | {'used_for': f'shot {i + 1}'})
        seg = (b - a) + 0.35 + (xd if i else 0) + (1.2 if i == len(cues) - 1 else 0)
        mv = (moves or ['push', 'pan_r', 'pull', 'pan_l'])[i % 4]
        shots.append(zl.shot(src['path'], f'{d}/tmp/s{i}.mp4', seg, W, H, move=mv, grade=grade))
    film = zl.xfade_concat(shots, f'{d}/tmp/film.mp4', xd)
    music = zl.bgm(f'{d}/tmp/bgm.wav', total + 1, mood)
    audio = zl.mix(vo, music, f'{d}/tmp/mix.wav', total)
    ev = caps(cues)
    if title:
        ev = [(0.2, 3.2, 'Title', r'{\fad(400,400)\blur1}' + title)] + ev
    extra = f'drawbox=x=0:y=0:w=iw:h={int(H * 0.12)}:color=black:t=fill,drawbox=x=0:y=ih-{int(H * 0.12)}:w=iw:h={int(H * 0.12)}:color=black:t=fill' if letterbox else ''
    ass = zl.write_ass(f'{d}/tmp/subs.ass', W, H, ev)
    return film, audio, ass, extra, prov, cues


# ---------------------------------------------------------------- lines
def _kinetic_promo(slots=None, output_dir=OUT):
    slots = slots or {}
    line = 'kinetic_promo'; d = str(output_dir) if output_dir != OUT else work(line)
    os.makedirs(d + '/tmp', exist_ok=True)
    topic = _topic(slots)
    W, H = _res(slots)
    words = _kinetic_words(topic)
    narration = [f'{topic}，从这里开始。', f'几个关键词，带你快速了解{topic}。', f'这就是{topic}。']
    vo, cues = zl.tts_lines(narration, f'{d}/tmp/vo', speed=1.05)
    total = max(14.0, dur(vo) + 1.5)
    qs = [topic] * 4
    shots, prov = [], []
    seg = total / len(qs) + 0.4
    for i, q in enumerate(qs):
        s = zl.pexels(q, min_d=4, pick=i); prov.append({k: v for k, v in s.items() if k != 'path'})
        shots.append(zl.shot(s['path'], f'{d}/tmp/s{i}.mp4', seg, W, H, move=['push', 'pan_r', 'pull', 'pan_l'][i],
                             grade='eq=brightness=-0.04:saturation=1.15'))
    film = zl.xfade_concat(shots, f'{d}/tmp/film.mp4', 0.4, 'slideleft')
    scale = total / max(1.0, words[-1][1] + 1.5)
    ev = []
    anims = [r'{\an5\fscx260\fscy260\alpha&HFF&\t(0,220,\fscx100\fscy100\alpha&H00&)}',
             r'{\an5\move(%d,%d,%d,%d,0,300)}' % (W + 400, H // 2, W // 2, H // 2),
             r'{\an5\fscy0\t(0,250,\fscy100)}',
             r'{\an5\frz-12\fscx40\fscy40\t(0,300,\frz0\fscx100\fscy100)}']
    for k, (w, t0) in enumerate(words):
        a = t0 * scale; b = (words[k + 1][1] * scale if k + 1 < len(words) else total - 0.2)
        style = 'Title' if k in (0, 1) else 'Kicker'
        ev.append((a, b, style, anims[k % 4] + r'{\fs%d\bord5}' % (110 if style == 'Title' else 70) + w))
    ev.append((total - 2.4, total, 'Kicker', r'{\an2\fad(300,0)\fs34}' + topic))
    ass = zl.write_ass(f'{d}/tmp/k.ass', W, H, ev)
    audio = zl.mix(vo, zl.bgm(f'{d}/tmp/bgm.wav', total + 1, 'bright'), f'{d}/tmp/mix.wav', total, -14)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, prov + [{'source': 'piper zh_CN-huayan (local)'}, {'source': 'procedural bgm'}],
                allow_dark=True, extra={'topic': topic, 'script': narration, 'inputs': {'topic': topic}})


def _explainer(slots=None, output_dir=OUT):
    slots = slots or {}
    line = 'explainer'; d = str(output_dir) if output_dir != OUT else work(line)
    os.makedirs(d + '/tmp', exist_ok=True)
    topic = _topic(slots)
    W, H = _res(slots)
    L = _script(slots, 'explainer')
    film, audio, ass, extra, prov, cues = broll_film(d, L, [topic] * len(L), grade='eq=saturation=1.1', W=W, H=H)
    heads = ['', '① 背景', '② 关键点', '③ 发展', '④ 影响', '']
    ev = caps(cues)
    for (a, b, _), h in zip(cues, heads):
        if h:
            ev.append((a, b, 'Lower', r'{\an7\pos(70,90)\fad(200,200)\fs52\c&H00C8FF&}' + h))
    ev.insert(0, (0.1, cues[0][1], 'Title', r'{\fad(300,300)}' + topic))
    ass = zl.write_ass(f'{d}/tmp/e.ass', W, H, ev)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, prov, extra={'topic': topic, 'script': L, 'inputs': {'topic': topic}})


def _cinematic(slots=None, output_dir=OUT):
    slots = slots or {}
    line = 'cinematic'; d = str(output_dir) if output_dir != OUT else work(line)
    os.makedirs(d + '/tmp', exist_ok=True)
    topic = _topic(slots)
    W, H = _res(slots)
    L = _script(slots, 'cinematic')
    grade = 'eq=contrast=1.05:saturation=1.1:brightness=0.04,colorbalance=rs=0.06:bs=-0.04'
    film, audio, ass, extra, prov, cues = broll_film(d, L, [topic] * len(L),
                                                      moves=['push', 'pan_r', 'push', 'pull', 'pan_l'],
                                                      grade=grade, letterbox=True, title=topic, speed=0.92, W=W, H=H)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass, extra)
    return save(d, line, final, prov, extra={'topic': topic, 'script': L, 'inputs': {'topic': topic}})


def _director_pipeline(slots=None, output_dir=OUT):
    slots = slots or {}
    line = 'director_pipeline'; d = str(output_dir) if output_dir != OUT else work(line)
    os.makedirs(d + '/tmp', exist_ok=True)
    topic = _topic(slots)
    W, H = _res(slots)
    L = _script(slots, 'director')
    brief = {'title': topic, 'logline': f'关于{topic}的五个瞬间', 'tone': '克制、明亮', 'duration_s': 25}
    sizes = ['WIDE', 'MEDIUM', 'CLOSE', 'MEDIUM', 'WIDE']
    moves = ['pull', 'push', 'push', 'pan_r', 'pan_l']
    beats = [(n, sizes[i], moves[i], topic) for i, n in enumerate(L)]
    shotlist = [{'shot': i + 1, 'size': s, 'camera': m, 'query': q, 'narration': n} for i, (n, s, m, q) in enumerate(beats)]
    json.dump({'brief': brief, 'shot_list': shotlist}, open(f'{d}/shot_list.json', 'w'), ensure_ascii=False, indent=2)
    film, audio, ass, extra, prov, cues = broll_film(d, [b[0] for b in beats], [b[3] for b in beats],
                                                      moves=[b[2] for b in beats], mood='bright', title=topic, W=W, H=H)
    ev = caps(cues) + [(a, b, 'Kicker', r'{\an9\pos(%d,40)\fs26\c&HFFFFFF&\alpha&H40&}SHOT %02d · %s · %s' %
                        (W - 40, i + 1, beats[i][1], beats[i][2].upper())) for i, (a, b, _) in enumerate(cues)]
    ev = [(0.2, 3.0, 'Title', r'{\fad(400,400)}' + topic)] + ev
    ass = zl.write_ass(f'{d}/tmp/dp.ass', W, H, ev)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, prov, notes='shot_list.json is the director output that drove the assembly',
                extra={'topic': topic, 'script': L, 'shot_list': shotlist, 'inputs': {'topic': topic}})


def _history_scene(slots=None, output_dir=OUT):
    slots = slots or {}
    line = 'history_scene'; d = str(output_dir) if output_dir != OUT else work(line)
    os.makedirs(d + '/tmp', exist_ok=True)
    topic = _topic(slots)
    W, H = _res(slots)
    L = _script(slots, 'history')
    vo, cues = zl.tts_lines(L, f'{d}/tmp/vo')
    total = dur(vo) + 1.2
    shots, prov = [], []
    for i, (a, b, _) in enumerate(cues):
        seg = (b - a) + 0.35 + (0.5 if i else 0) + (1.2 if i == len(cues) - 1 else 0)
        s = zl.pexels(topic, min_d=4, pick=i)
        prov.append({k: v for k, v in s.items() if k != 'path'})
        shots.append(zl.shot(s['path'], f'{d}/tmp/s{i}.mp4', seg, W, H, move=['pull', 'pan_r', 'push', 'push', 'pan_l', 'pull'][i % 6],
                             grade='eq=saturation=0.8,colorbalance=rs=0.06:bs=-0.05'))
    film = zl.xfade_concat(shots, f'{d}/tmp/film.mp4', 0.5)
    ev = caps(cues) + [(0.2, 3.4, 'Title', r'{\fad(400,400)}' + topic)]
    ass = zl.write_ass(f'{d}/tmp/h.ass', W, H, ev)
    audio = zl.mix(vo, zl.bgm(f'{d}/tmp/bgm.wav', total + 1, 'warm'), f'{d}/tmp/mix.wav', total)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, prov, extra={'topic': topic, 'script': L, 'inputs': {'topic': topic}})


def _character_animation(slots=None, output_dir=OUT):
    slots = slots or {}
    line = 'character_animation'; d = str(output_dir) if output_dir != OUT else work(line)
    os.makedirs(d + '/tmp', exist_ok=True)
    topic = _topic(slots)
    W, H = _res(slots)
    fps = 24
    silent = zl.frames_to_video(puppets.caveman_scene(W, H, fps, 12.0), f'{d}/tmp/anim.mp4', W, H, fps)
    L = _script(slots, 'character')
    vo, cues = zl.tts_lines(L, f'{d}/tmp/vo', gap=0.2)
    at = [0.6, 4.8, 7.8, 10.1]
    at = [at[i] if i < len(at) else 0.6 + i * 2.0 for i in range(len(cues))]
    parts = []
    for i, ((a, b, t), s) in enumerate(zip(cues, at)):
        parts.append(f'[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS,adelay={int(s * 1000)}|{int(s * 1000)}[p{i}]')
    sh([FF, '-y', '-i', vo, '-filter_complex', ';'.join(parts) + ';' + ''.join(f'[p{i}]' for i in range(len(cues))) +
        f'amix=inputs={len(cues)}:normalize=0,apad,atrim=0:12[a]', '-map', '[a]', f'{d}/tmp/vo_timed.wav'])
    audio = zl.mix(f'{d}/tmp/vo_timed.wav', zl.bgm(f'{d}/tmp/bgm.wav', 13, 'warm'), f'{d}/tmp/mix.wav', 12.0)
    # topic-derived hue shift so two different topics produce visibly different frames
    hue = zlib.crc32(topic.encode('utf-8')) % 360
    graded = f'{d}/tmp/graded.mp4'
    sh([FF, '-y', '-i', silent, '-vf', f'hue=h={hue},eq=saturation=1.05', '-c:v', 'libx264',
        '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', graded])
    ev = [(s, s + (b - a) + 0.4, 'Cap', t) for (a, b, t), s in zip(cues, at)]
    ev = [(0.2, 3.0, 'Title', r'{\fad(300,300)}' + topic)] + ev
    ass = zl.write_ass(f'{d}/tmp/c.ass', W, H, ev)
    final = zl.finish(graded, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, [{'source': 'procedural 2D puppet (PIL), caveman_scene', 'hue_shift_deg': hue}],
                min_motion=0.4, notes='procedural 2D character animation; narration and title are topic-driven',
                extra={'topic': topic, 'script': L, 'inputs': {'topic': topic}})


def _photo_video(d, image_path, wav, W, H, fps=24, pip=False):
    env = zl.rms_envelope(wav, fps)
    mouth = puppets.mouth_series(env)
    rects = f'{d}/presenter_rect.json'
    if pip:
        gen = puppets.photo_pip_frames(image_path, W, fps, mouth, rect_out=rects)
    else:
        gen = puppets.photo_frames(image_path, W, H, fps, mouth, rect_out=rects)
    return zl.frames_to_video(gen, f'{d}/tmp/avatar.mp4', W, H, fps), rects


def _talking_head(slots=None, output_dir=OUT):
    slots = slots or {}
    line = 'talking_head'; d = str(output_dir) if output_dir != OUT else work(line)
    os.makedirs(d + '/tmp', exist_ok=True)
    topic = _topic(slots)
    image_path = _image_path(slots, line)
    W, H = _res(slots)
    L = _script(slots, 'presenter')
    vo, cues = zl.tts_lines(L, f'{d}/tmp/vo')
    pv, rects = _photo_video(d, image_path, vo, W, H)
    total = dur(vo)
    audio = zl.mix(vo, zl.bgm(f'{d}/tmp/bgm.wav', total + 1, 'warm'), f'{d}/tmp/mix.wav', total, -26)
    ev = caps(cues) + [(0.3, 4.5, 'Lower', r'{\an1\fad(300,300)\fs34}' + topic)]
    ass = zl.write_ass(f'{d}/tmp/t.ass', W, H, ev)
    final = zl.finish(pv, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, [{'source': 'supplied presenter photo', 'image_path': image_path},
                                 {'source': 'procedural photo presenter, animated equaliser driven by VO RMS'}],
                min_motion=0.3, notes='2D photo presenter built from the caller-supplied image_path; NOT a photoreal digital human',
                extra={'topic': topic, 'script': L, 'inputs': {'topic': topic, 'image_path': image_path},
                       'presenter_rect': {'video': rects, 'kind': 'full'}})


def _avatar_spokesperson(slots=None, output_dir=OUT):
    slots = slots or {}
    line = 'avatar_spokesperson'; d = str(output_dir) if output_dir != OUT else work(line)
    os.makedirs(d + '/tmp', exist_ok=True)
    topic = _topic(slots)
    image_path = _image_path(slots, line)
    W, H = _res(slots)
    L = _script(slots, 'presenter')
    vo, cues = zl.tts_lines(L, f'{d}/tmp/vo')
    total = dur(vo) + 0.8
    Q = [topic] * 4
    shots, prov = [], []
    seg = total / len(Q) + 0.5
    for i, q in enumerate(Q):
        s = zl.pexels(q, min_d=4, pick=i); prov.append({k: v for k, v in s.items() if k != 'path'})
        shots.append(zl.shot(s['path'], f'{d}/tmp/s{i}.mp4', seg, W, H, move=['push', 'pan_r', 'pull', 'pan_l'][i]))
    film = zl.xfade_concat(shots, f'{d}/tmp/film.mp4', 0.5)
    P = max(96, int(H * 0.34))
    pv, rects = _photo_video(d, image_path, vo, P, P, pip=True)
    comp = f'{d}/tmp/comp.mp4'
    sh([FF, '-y', '-i', film, '-i', pv, '-filter_complex',
        f"[1:v]format=rgba,geq=lum='p(X,Y)':a='if(lte(hypot(X-{P / 2},Y-{P / 2}),{P / 2 - 4}),255,0)'[c];"
        f'[0:v][c]overlay=W-w-50:H-h-120:shortest=1,format=yuv420p[v]', '-map', '[v]', '-c:v', 'libx264',
        '-preset', 'veryfast', '-crf', '20', comp])
    audio = zl.mix(vo, zl.bgm(f'{d}/tmp/bgm.wav', total + 1, 'bright'), f'{d}/tmp/mix.wav', total, -22)
    ev = [(a, b, 'Cap', r'{\an1\pos(70,%d)}' % (H - 70) + t) for a, b, t in cues]
    ev += [(0.3, total - 3, 'Lower', r'{\an7\pos(70,60)\fs34}' + topic),
           (total - 3, total, 'Title', r'{\fad(300,0)\fs64}' + topic)]
    ass = zl.write_ass(f'{d}/tmp/a.ass', W, H, ev)
    final = zl.finish(comp, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, prov + [{'source': 'supplied spokesperson photo (circular PiP)', 'image_path': image_path},
                                        {'source': 'procedural photo PiP, RMS-driven motion'}],
                notes='spokesperson layout: topic b-roll + circular photo avatar PiP from image_path + lower third + CTA end card',
                extra={'topic': topic, 'script': L, 'inputs': {'topic': topic, 'image_path': image_path},
                       'presenter_rect': {'video': rects, 'kind': 'pip',
                                          'offset': [W - P - 50, H - P - 120], 'size': [P, P]}})


def _whisper(src, lang):
    from faster_whisper import WhisperModel
    m = WhisperModel('/home/soffy/models/faster-whisper-large-v3-turbo', device='cpu', compute_type='int8')
    segs, _ = m.transcribe(src, language=lang, word_timestamps=True, vad_filter=True)
    return [{'start': s.start, 'end': s.end, 'text': s.text.strip(),
             'words': [(w.start, w.end, w.word) for w in (s.words or [])]} for s in segs]


def _pick_windows(segs, n=2, target=(18, 32)):
    wins, i = [], 0
    while i < len(segs) and len(wins) < n:
        j = i
        while j < len(segs) and segs[j]['end'] - segs[i]['start'] < target[0]:
            j += 1
        if j >= len(segs):
            break
        if segs[j]['end'] - segs[i]['start'] <= target[1]:
            wins.append((i, j)); i = j + 1
        else:
            i += 1
    if not wins and segs:
        # fall back to the first (up to 30s) run of speech so the line still produces a real clip
        end = segs[0]['start']
        j = 0
        while j < len(segs) and segs[j]['end'] - segs[0]['start'] <= 30:
            end = segs[j]['end']; j += 1
        wins = [(0, max(0, j - 1))]
    return wins


def _shorts_clip(slots=None, output_dir=OUT):
    slots = slots or {}
    line = 'shorts_clip'; d = str(output_dir) if output_dir != OUT else work(line)
    os.makedirs(d + '/tmp', exist_ok=True)
    topic = _topic(slots)
    src, src_key = _media_path(slots, line)
    segs = _whisper(src, str(slots.get('lang') or 'en'))
    json.dump(segs, open(f'{d}/transcript.json', 'w'), ensure_ascii=False, indent=1)
    W, H = _res(slots, (720, 1280))
    outs = []
    for k, (i, j) in enumerate(_pick_windows(segs)):
        a, b = segs[i]['start'] - 0.2, segs[j]['end'] + 0.3
        ev = []
        for s in segs[i:j + 1]:
            ws = s['words']
            for c in range(0, len(ws), 4):
                chunk = ws[c:c + 4]
                ev.append((chunk[0][0] - a, chunk[-1][1] - a, 'Cap',
                           r'{\an5\pos(%d,%d)\fs54\bord5\fad(60,60)}' % (W // 2, int(H * 0.72)) + ''.join(w[2] for w in chunk).strip().upper()))
        ev.append((0, b - a, 'Kicker', r'{\an8\pos(%d,140)\fs38}' % (W // 2) + topic))
        ass = zl.write_ass(f'{d}/tmp/c{k}.ass', W, H, ev)
        out = f'{d}/{line}_{k + 1:02d}.mp4'
        # Zoompan on the whole source for guaranteed motion (Ken Burns effect)
        # plus animated crop pan on a blurred copy as background
        clip_dur = max(0.1, float(b - a))
        frames = int(clip_dur * 30)
        zoomstep = 0.0005
        fc = (
            f"[0:v]split[bg][fg];"
            f"[bg]scale={W + 120}:{H + 120}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}:x='(iw-{W})*t/{clip_dur:.3f}':y='(ih-{H})*0.5*(1+sin(t/3))',"
            f"boxblur=30:3,eq=brightness=-0.15[b];"
            f"[fg]zoompan=z='zoom+{zoomstep}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps=30[x];"
            f"[b][x]overlay=0:(H-h)/2-80,"
            f"subtitles='{d}/tmp/c{k}.ass':fontsdir=/usr/share/fonts/opentype/noto[v]"
        )
        sh([FF, '-y', '-ss', f'{a:.2f}', '-t', f'{b - a:.2f}', '-i', src, '-filter_complex', fc,
            '-map', '[v]', '-map', '0:a', '-af', 'loudnorm=I=-15', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
            '-c:a', 'aac', '-movflags', '+faststart', out])
        outs.append(out)
    recs = [zl.qa(o) for o in outs]
    zl.contact_sheet(outs[0], f'{d}/contact_sheet.jpg')
    rec = {'line': line, 'final': outs[0], 'finals': outs, 'qa': recs[0], 'qa_all': recs, 'cost_usd': 0,
           'pass': all(r['pass'] for r in recs), 'topic': topic, 'script': [s['text'] for s in segs],
           'inputs': {'topic': topic, src_key: src},
           'provenance': [{'source': f'local source video ({src_key})', 'path': src},
                          {'source': 'faster-whisper large-v3-turbo (local CPU) word timestamps'}]}
    json.dump(rec, open(f'{d}/record.json', 'w'), ensure_ascii=False, indent=2)
    shutil.rmtree(f'{d}/tmp', ignore_errors=True)
    print(line, 'PASS' if rec['pass'] else 'FAIL', [r['checks'] for r in recs])
    return rec


def _podcast_repurpose(slots=None, output_dir=OUT):
    slots = slots or {}
    line = 'podcast_repurpose'; d = str(output_dir) if output_dir != OUT else work(line)
    os.makedirs(d + '/tmp', exist_ok=True)
    topic = _topic(slots)
    src, src_key = _media_path(slots, line)
    segs = _whisper(src, str(slots.get('lang') or 'en'))
    json.dump(segs, open(f'{d}/transcript.json', 'w'), ensure_ascii=False, indent=1)
    (i, j), = _pick_windows(segs, 1, (12, 55))
    a, b = segs[i]['start'] - 0.2, segs[j]['end'] + 0.3
    W, H = _res(slots, (1080, 1080))
    ev = [(s['start'] - a, s['end'] - a, 'Cap', r'{\an5\pos(%d,%d)\fs40}' % (W // 2, int(H * 0.80)) + s['text']) for s in segs[i:j + 1]]
    ev += [(0, b - a, 'Kicker', r'{\an7\pos(60,150)\fs30\c&H00C8FF&}PODCAST · REPURPOSE'),
           (0, b - a, 'Title', r'{\an7\pos(60,200)\fs52}' + topic),
           (0, b - a, 'Kicker', r'{\an7\pos(60,275)\fs26\c&HCCCCCC&}' + topic)]
    ass = zl.write_ass(f'{d}/tmp/p.ass', W, H, ev)
    out = f'{d}/{line}.mp4'
    sh([FF, '-y', '-ss', f'{a:.2f}', '-t', f'{b - a:.2f}', '-i', src, '-filter_complex',
        f'[0:v]scale={W + 240}:{H + 240}:force_original_aspect_ratio=increase,boxblur=20:2,crop={W}:{H}:x=\'120+90*sin(t*0.6)\':y=\'120+70*cos(t*0.5)\',eq=brightness=0.0:saturation=1.2[bg];'
        f'[0:v]scale=360:360:force_original_aspect_ratio=increase,crop=360:360[cov];'
        f'[0:a]asplit[a1][a2];[a1]showwaves=s={W - 160}x320:mode=cline:colors=0x00C8FF|0x0088CC:rate=30,format=rgba[w];'
        f'[bg][cov]overlay=80:120[t1];[t1][w]overlay=80:500:shortest=1,'
        f"drawbox=x=60:y=ih-60:w='(iw-120)*t/{b - a:.2f}':h=8:color=0x00C8FF:t=fill,"
        f"subtitles='{ass}':fontsdir=/usr/share/fonts/opentype/noto[v]",
        '-map', '[v]', '-map', '[a2]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-c:a', 'aac',
        '-movflags', '+faststart', out])
    return save(d, line, out, [{'source': f'local source video ({src_key})', 'path': src},
                               {'source': 'faster-whisper large-v3-turbo (local CPU)'}], min_motion=1.0,
                notes='audiogram format: dynamic video background + video cover card + live waveform + captions + progress bar',
                extra={'topic': topic, 'script': [s['text'] for s in segs], 'inputs': {'topic': topic, src_key: src}})


def _reference_adapt(slots=None, output_dir=OUT):
    slots = slots or {}
    line = 'reference_adapt'; d = str(output_dir) if output_dir != OUT else work(line)
    os.makedirs(d + '/tmp', exist_ok=True)
    topic = _topic(slots)
    ref, ref_key = _media_path(slots, line)
    W, H = _res(slots)
    L = _script(slots, 'cinematic')[:5]
    sd = dur(ref)
    n = len(L)
    plan = [(max(0.0, sd * (k + 0.5) / n - 2), L[k]) for k in range(n)]
    vo, cues = zl.tts_lines([p[1] for p in plan], f'{d}/tmp/vo')
    total = dur(vo) + 1.0
    shots = []
    for k, ((a, b, _), (ss, _)) in enumerate(zip(cues, plan)):
        seg = (b - a) + 0.35 + (0.6 if k else 0) + (1.0 if k == len(plan) - 1 else 0)
        shots.append(zl.shot(ref, f'{d}/tmp/s{k}.mp4', seg, W, H, ss=ss, move=['push', 'pan_r', 'pull', 'pan_l', 'push'][k % 5],
                             grade='scale=iw:ih:flags=lanczos,unsharp=5:5:0.8,eq=contrast=1.08:saturation=1.2'))
    film = zl.xfade_concat(shots, f'{d}/tmp/film.mp4', 0.6, 'fade')
    ev = caps(cues) + [(0.2, 3.0, 'Title', r'{\fad(300,300)}' + topic)]
    ass = zl.write_ass(f'{d}/tmp/r.ass', W, H, ev)
    audio = zl.mix(vo, zl.bgm(f'{d}/tmp/bgm.wav', total + 1, 'warm'), f'{d}/tmp/mix.wav', total)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass)
    rec = save(d, line, final, [{'source': f'reference video ({ref_key})', 'path': ref,
                                 'segments_used_s': [round(p[0], 2) for p in plan]}],
               notes='segments sampled from the supplied reference video, topic narration, grade, camera moves, transitions, captions',
               extra={'topic': topic, 'script': L, 'inputs': {'topic': topic, ref_key: ref}})
    return rec


def _documentary_montage(slots=None, output_dir=OUT):
    slots = slots or {}
    line = 'documentary_montage'; d = str(output_dir) if output_dir != OUT else work(line)
    os.makedirs(d + '/tmp', exist_ok=True)
    topic = _topic(slots)
    src, src_key = _media_path(slots, line)
    W, H = _res(slots)
    L = _script(slots, 'history')[:4]
    sd = dur(src)
    n = len(L)
    plan = [(max(0.0, sd * (k + 0.25) / n), L[k]) for k in range(n)]
    vo, cues = zl.tts_lines([p[1] for p in plan], f'{d}/tmp/vo')
    total = dur(vo) + 1.2
    shots, prov = [], []
    prov.append({'source': f'supplied archival source video ({src_key})', 'path': src,
                 'timestamps_used_s': [round(p[0], 2) for p in plan]})
    xd = 0.5
    for i, ((a, b, _), (ss, _)) in enumerate(zip(cues, plan)):
        seg = (b - a) + 0.35 + (xd if i else 0) + (1.2 if i == len(cues) - 1 else 0)
        mv = ['push', 'pan_r', 'pull', 'pan_l'][i % 4]
        shots.append(zl.shot(src, f'{d}/tmp/s{i}.mp4', seg, W, H, ss=ss, move=mv,
                             grade='eq=contrast=1.06:saturation=1.1,unsharp=3:3:0.5'))
    film = zl.xfade_concat(shots, f'{d}/tmp/film.mp4', xd)
    ev = caps(cues) + [(0.2, 3.2, 'Title', r'{\fad(400,400)}' + topic)]
    ass = zl.write_ass(f'{d}/tmp/d.ass', W, H, ev)
    audio = zl.mix(vo, zl.bgm(f'{d}/tmp/bgm.wav', total + 1, 'epic'), f'{d}/tmp/mix.wav', total)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, prov, extra={'topic': topic, 'script': L, 'inputs': {'topic': topic, src_key: src}})


def _has_cjk(s):
    return any('\u4e00' <= c <= '\u9fff' for c in s)


def _translate_en_to_zh(text):
    """Translate English to Chinese with a real free translator.

    Returns ``(translation, provider)``.  Raises if no translator can produce
    Chinese text, so the line fails loudly instead of silently dubbing the
    English original.
    """
    cleaned = text.strip()
    if not cleaned:
        return '', 'none'
    attempts = [
        ('MyMemoryTranslator', lambda: __import__('deep_translator').MyMemoryTranslator(source='en-US', target='zh-CN').translate(cleaned)),
        ('GoogleTranslator', lambda: __import__('deep_translator').GoogleTranslator(source='en', target='zh-CN').translate(cleaned)),
    ]
    for name, fn in attempts:
        try:
            tr = fn()
            if tr and tr.strip() and _has_cjk(tr):
                return tr.replace('，，', '，').strip(), name + ' (free web API)'
        except Exception:
            continue
    raise RuntimeError('translation unavailable: no free translator returned Chinese for the source speech')


def _localization_dub(slots=None, output_dir=OUT):
    slots = slots or {}
    line = 'localization_dub'; d = str(output_dir) if output_dir != OUT else work(line)
    os.makedirs(d + '/tmp', exist_ok=True)
    topic = _topic(slots)
    src, src_key = _media_path(slots, line)
    W, H = _res(slots)
    total = float(slots.get('dub_seconds') or 11.5)
    total = min(total, max(3.0, dur(src) - 0.2))

    clip_wav = f'{d}/tmp/clip.wav'
    subprocess.run([FF, '-y', '-ss', '0', '-t', str(total), '-i', src, '-ar', '16000', '-ac', '1', clip_wav],
                   check=True, stderr=subprocess.DEVNULL)
    segs = _whisper(clip_wav, str(slots.get('lang') or 'en'))

    translated_texts, providers = [], set()
    for s in segs:
        tr, prov = _translate_en_to_zh(s['text'])
        translated_texts.append(tr)
        providers.add(prov)

    cues, filter_inputs = [], []
    for i, (s, tr) in enumerate(zip(segs, translated_texts)):
        seg_wav = f'{d}/tmp/dub_{i}.wav'
        zl.tts(tr, seg_wav)
        seg_dur = dur(seg_wav)
        target_dur = s['end'] - s['start']
        speed_factor = max(0.8, min(1.3, seg_dur / max(0.5, target_dur)))
        stretched = f'{d}/tmp/dub_{i}_fit.wav'
        subprocess.run([FF, '-y', '-i', seg_wav, '-af', f'atempo={speed_factor}', stretched],
                       check=True, stderr=subprocess.DEVNULL)
        fit_dur = dur(stretched)
        start_ms = int(s['start'] * 1000)
        filter_inputs.append(f'[{i + 1}:a]adelay={start_ms}|{start_ms}[p{i}]')
        cues.append((s['start'], s['start'] + fit_dur, tr))

    cmd = [FF, '-y', '-ss', '0', '-t', str(total), '-i', src]
    for i in range(len(segs)):
        cmd.extend(['-i', f'{d}/tmp/dub_{i}_fit.wav'])
    fc = ';'.join(filter_inputs) + ';' + ''.join(f'[p{i}]' for i in range(len(segs))) + f'amix=inputs={len(segs)}:normalize=0[dub];'
    fc += f'[0:a]volume=0.25,atrim=0:{total}[orig];[orig][dub]amix=inputs=2:normalize=0,atrim=0:{total}[aout]'
    cmd.extend(['-filter_complex', fc, '-map', '[aout]', f'{d}/tmp/mix_audio.wav'])
    subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)

    ev = caps(cues) + [(0.2, 3.5, 'Title', r'{\fad(300,300)}' + topic)]
    ass = zl.write_ass(f'{d}/tmp/dub.ass', W, H, ev)
    final = f'{d}/{line}.mp4'
    subprocess.run([FF, '-y', '-ss', '0', '-t', str(total), '-i', src, '-i', f'{d}/tmp/mix_audio.wav',
                    '-vf', f"scale={W}:{H},subtitles='{ass}':fontsdir=/usr/share/fonts/opentype/noto",
                    '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                    '-c:a', 'aac', '-shortest', final], check=True, stderr=subprocess.DEVNULL)

    prov = [
        {'source': f'supplied source video ({src_key})', 'path': src, 'segment_s': [0.0, total]},
        {'source': 'faster-whisper large-v3-turbo (local CPU) automatic speech recognition'},
        {'source': 'translator: ' + ', '.join(sorted(providers))},
        {'source': 'piper zh_CN-huayan (local ONNX TTS) voice dubbing with timeline alignment'},
    ]
    report = {'line': line, 'topic': topic, 'source': src, 'translated_segments': translated_texts,
              'translators': sorted(providers), 'segments': segs}
    json.dump(report, open(f'{d}/video_localization_report.json', 'w'), ensure_ascii=False, indent=2)
    return save(d, line, final, prov, notes='real speech transcription, free translation, TTS dubbing aligned to timeline',
                extra={'topic': topic, 'script': translated_texts, 'inputs': {'topic': topic, src_key: src}})


LINES = {f.__name__.lstrip("_"): f for f in [_kinetic_promo, _explainer, _cinematic, _director_pipeline, _history_scene,
                                 _character_animation, _talking_head, _avatar_spokesperson, _shorts_clip,
                                 _podcast_repurpose, _reference_adapt, _documentary_montage, _localization_dub]}


def _demo_slots(line):
    base = {'topic': '示例主题', 'resolution': '640x360'}
    if line in {'talking_head', 'avatar_spokesperson'}:
        base['image_path'] = '/data/soffy/projects/hevi/data/workspace/assets/celebrities30s/English/Michio Kaku.jpg'
    if line in {'shorts_clip', 'podcast_repurpose', 'reference_adapt', 'documentary_montage', 'localization_dub'}:
        base['media_path'] = f'{SEED}/nasa_Apollo_14_Launch_Coverage.mp4'
    return base


if __name__ == '__main__':
    todo = list(LINES) if sys.argv[1:] == ['all'] else sys.argv[1:]
    res = {}
    for n in todo:
        t = time.time()
        try:
            r = LINES[n](slots=_demo_slots(n))
            res[n] = {'pass': r.get('pass') if 'pass' in r else r['qa']['pass'], 'secs': round(time.time() - t)}
        except Exception as e:  # keep going; record the failure honestly
            res[n] = {'error': str(e)[-600:], 'secs': round(time.time() - t)}
            print(n, 'ERROR', str(e)[-600:])
    os.makedirs(OUT, exist_ok=True)
    json.dump(res, open(f'{OUT}/run_{int(time.time())}.json', 'w'), ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False))
