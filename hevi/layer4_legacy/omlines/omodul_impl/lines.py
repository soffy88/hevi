"""hevi-zero line producers. Usage: python lines.py <line> [<line> ...] | all"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
import numpy as np
import zl
from zl import FF, sh, dur
import puppets

OUT = f'{zl.ROOT}/out'
SEED = '/data/soffy/projects/hevi/data/workspace/assets/open-corpus-seed/clips'
LW, LH = 1280, 720


def work(line):
    d = f'{OUT}/{line}'
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d + '/tmp', exist_ok=True)
    return d


def caps(cues, style='Cap'):
    return [(a, b, style, t) for a, b, t in cues]


def save(d, line, final, prov, expect_audio=True, min_motion=1.0, notes='', allow_dark=False):
    q = zl.qa(final, expect_audio, min_motion)
    if allow_dark:  # night/cave scenes are dark by design: report the ratios but do not gate on them
        q['waived'] = {k: q['checks'].pop(k) for k in ('black_ratio_lt_0.1', 'dark_textcard_ratio_lt_0.5')}
        q['pass'] = all(q['checks'].values())
    zl.contact_sheet(final, f'{d}/contact_sheet.jpg')
    rec = {'line': line, 'final': final, 'cost_usd': 0, 'gpu': False, 'paid_api': False,
           'provenance': prov, 'qa': q, 'notes': notes,
           'produced_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
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
        src = zl.pexels(q, orient, min_d=4, pick=(picks or [0] * 99)[i])
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
def kinetic_promo():
    line = 'kinetic_promo'; d = work(line)
    words = [('七十万年前', 0.0), ('有人在这里', 1.6), ('点燃了第一堆火', 3.0), ('周口店', 5.2),
             ('北京人遗址', 6.6), ('这个秋天', 8.8), ('去看看', 10.0), ('人类从哪里来', 11.2)]
    vo, cues = zl.tts_lines(['七十万年前，有人在这里点燃了第一堆火。', '周口店，北京人遗址。', '这个秋天，去看看人类从哪里来。'],
                            f'{d}/tmp/vo', speed=1.05)
    total = max(14.0, dur(vo) + 1.5)
    qs = ['campfire night', 'limestone cave', 'ancient stone tools', 'autumn mountain forest']
    shots, prov = [], []
    seg = total / len(qs) + 0.4
    for i, q in enumerate(qs):
        s = zl.pexels(q, min_d=4); prov.append({k: v for k, v in s.items() if k != 'path'})
        shots.append(zl.shot(s['path'], f'{d}/tmp/s{i}.mp4', seg, LW, LH, move=['push', 'pan_r', 'pull', 'pan_l'][i],
                             grade='eq=brightness=-0.04:saturation=1.15'))
    film = zl.xfade_concat(shots, f'{d}/tmp/film.mp4', 0.4, 'slideleft')
    # kinetic typography: per-word slam/slide/scale with ASS transforms, timed across the film
    scale = total / 14.0
    ev = []
    anims = [r'{\an5\fscx260\fscy260\alpha&HFF&\t(0,220,\fscx100\fscy100\alpha&H00&)}',
             r'{\an5\move(%d,%d,%d,%d,0,300)}' % (LW + 400, LH // 2, LW // 2, LH // 2),
             r'{\an5\fscy0\t(0,250,\fscy100)}',
             r'{\an5\frz-12\fscx40\fscy40\t(0,300,\frz0\fscx100\fscy100)}']
    for k, (w, t0) in enumerate(words):
        a = t0 * scale; b = (words[k + 1][1] * scale if k + 1 < len(words) else total - 0.2)
        style = 'Title' if k in (3, 4, 7) else 'Kicker'
        ev.append((a, b, style, anims[k % 4] + r'{\fs%d\bord5}' % (110 if style == 'Title' else 70) + w))
    ev.append((total - 2.4, total, 'Kicker', r'{\an2\fad(300,0)\fs34}周口店北京人遗址博物馆 · 北京房山'))
    ass = zl.write_ass(f'{d}/tmp/k.ass', LW, LH, ev)
    audio = zl.mix(vo, zl.bgm(f'{d}/tmp/bgm.wav', total + 1, 'bright'), f'{d}/tmp/mix.wav', total, -14)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, prov + [{'source': 'piper zh_CN-huayan (local)'}, {'source': 'procedural bgm'}], allow_dark=True)


def explainer():
    line = 'explainer'; d = work(line)
    L = ['火，对早期人类意味着什么？', '第一，取暖。火让人类能在寒冷的季节和夜晚活下来。',
         '第二，防御。火光和烟能让野兽保持距离。', '第三，熟食。加热后的食物更容易咀嚼和消化。',
         '第四，聚集。围着火堆，人们开始在夜里交流、分享和学习。', '所以，学会用火，是人类历史上的一次关键转折。']
    Q = ['fire flames close up', 'people warming hands fire winter', 'wolf night forest', 'meat cooking open fire',
         'friends around campfire night', 'sunrise mountains']
    film, audio, ass, extra, prov, cues = broll_film(d, L, Q, grade='eq=saturation=1.1')
    heads = ['', '① 取暖', '② 防御', '③ 熟食', '④ 聚集', '']
    ev = caps(cues)
    for (a, b, _), h in zip(cues, heads):
        if h:
            ev.append((a, b, 'Lower', r'{\an7\pos(70,90)\fad(200,200)\fs52\c&H00C8FF&}' + h))
    ev.insert(0, (0.1, cues[0][1], 'Title', r'{\fad(300,300)}火，对早期人类意味着什么？'))
    ass = zl.write_ass(f'{d}/tmp/e.ass', LW, LH, ev)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, prov)


def cinematic():
    line = 'cinematic'; d = work(line)
    L = ['黑暗里，只有一支火把。', '火光贴着岩壁移动，照出前人留下的痕迹。', '石头相击，火星落进干草。',
         '他走向洞口。', '山谷在晨光里打开，新的一天开始了。']
    Q = ['burning torch in the dark', 'cave wall light exploration', 'striking flint sparks', 'cave entrance silhouette',
         'sunrise valley mist']
    grade = 'eq=contrast=1.12:saturation=0.85:gamma=0.95,colorbalance=rs=0.08:bs=-0.06:rh=0.05:bh=-0.05'
    film, audio, ass, extra, prov, cues = broll_film(d, L, Q, moves=['push', 'pan_r', 'push', 'pull', 'pan_l'],
                                                      grade=grade, letterbox=True, title='火 种', speed=0.92)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass, extra)
    return save(d, line, final, prov, allow_dark=True)


def director_pipeline():
    line = 'director_pipeline'; d = work(line)
    brief = {'title': '城市醒来', 'logline': '一座城市从凌晨到早高峰的五个瞬间', 'tone': '克制、明亮', 'duration_s': 25}
    # rule-based director: beat -> shot spec (size, camera, query, narration)
    beats = [('凌晨五点，城市还在沉睡。', 'WIDE', 'pull', 'city skyline dawn'),
             ('第一盏灯亮起，有人已经出门。', 'MEDIUM', 'push', 'window light morning apartment'),
             ('早餐摊的蒸汽升起来。', 'CLOSE', 'push', 'street food steam morning'),
             ('地铁载着第一批人穿过城市。', 'MEDIUM', 'pan_r', 'subway train arriving'),
             ('八点，街道彻底醒了。', 'WIDE', 'pan_l', 'busy crosswalk city timelapse')]
    shotlist = [{'shot': i + 1, 'size': s, 'camera': m, 'query': q, 'narration': n} for i, (n, s, m, q) in enumerate(beats)]
    json.dump({'brief': brief, 'shot_list': shotlist}, open(f'{d}/shot_list.json', 'w'), ensure_ascii=False, indent=2)
    film, audio, ass, extra, prov, cues = broll_film(d, [b[0] for b in beats], [b[3] for b in beats],
                                                      moves=[b[2] for b in beats], mood='bright', title='城市醒来')
    ev = caps(cues) + [(a, b, 'Kicker', r'{\an9\pos(%d,40)\fs26\c&HFFFFFF&\alpha&H40&}SHOT %02d · %s · %s' %
                        (LW - 40, i + 1, beats[i][1], beats[i][2].upper())) for i, (a, b, _) in enumerate(cues)]
    ev = [(0.2, 3.0, 'Title', r'{\fad(400,400)}城市醒来')] + ev
    ass = zl.write_ass(f'{d}/tmp/dp.ass', LW, LH, ev)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, prov, notes='shot_list.json is the director output that drove the assembly')


def history_scene():
    line = 'history_scene'; d = work(line)
    L = ['周口店遗址位于北京西南的房山区龙骨山。', '一九二一年起，学者们在这里开始调查和发掘。',
         '一九二九年十二月二日，裴文中发现了第一个北京人头盖骨。', '北京人生活在大约七十万到二十万年前，会打制石器，也会用火。',
         '一九四一年，头盖骨化石在战乱中下落不明，至今仍是未解之谜。', '一九八七年，周口店北京人遗址被列入世界文化遗产名录。']
    vo, cues = zl.tts_lines(L, f'{d}/tmp/vo')
    total = dur(vo) + 1.2
    wan = sorted(os.path.join(dp, f) for dp, _, fs in os.walk('/data/soffy/projects/hevi/data/cinematic_output/wan21_test') for f in fs if f.endswith('.mp4'))
    plan = [('pexels', 'limestone hill aerial'), ('pexels', 'archaeologist excavation dig'), ('wan', 0),
            ('pexels', 'stone tools flint'), ('pexels', 'old archive documents'), ('pexels', 'cave entrance green hill')]
    shots, prov = [], []
    for i, ((a, b, _), (kind, q)) in enumerate(zip(cues, plan)):
        seg = (b - a) + 0.35 + (0.5 if i else 0) + (1.2 if i == len(cues) - 1 else 0)
        if kind == 'wan' and wan:
            src = wan[q]; prov.append({'source': 'local Wan2.1 render (2026-08-08, existing asset)', 'path': src})
        else:
            s = zl.pexels(q, min_d=4); src = s['path']; prov.append({k: v for k, v in s.items() if k != 'path'})
        shots.append(zl.shot(src, f'{d}/tmp/s{i}.mp4', seg, LW, LH, move=['pull', 'pan_r', 'push', 'push', 'pan_l', 'pull'][i],
                             grade='eq=saturation=0.8,colorbalance=rs=0.06:bs=-0.05'))
    film = zl.xfade_concat(shots, f'{d}/tmp/film.mp4', 0.5)
    years = ['', '1921', '1929.12.2', '70万—20万年前', '1941', '1987']
    ev = caps(cues) + [(a, b, 'Lower', r'{\an7\pos(70,80)\fad(250,250)\fs56\c&H7FD7FF&}' + y) for (a, b, _), y in zip(cues, years) if y]
    ev = [(0.2, 3.4, 'Title', r'{\fad(400,400)}周口店 · 北京人')] + ev
    ass = zl.write_ass(f'{d}/tmp/h.ass', LW, LH, ev)
    audio = zl.mix(vo, zl.bgm(f'{d}/tmp/bgm.wav', total + 1, 'warm'), f'{d}/tmp/mix.wav', total)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, prov)


def character_animation():
    line = 'character_animation'; d = work(line)
    fps = 24
    silent = zl.frames_to_video(puppets.caveman_scene(LW, LH, fps, 12.0), f'{d}/tmp/anim.mp4', LW, LH, fps)
    vo, cues = zl.tts_lines(['他走向洞口。', '弯腰，捡起一块石头。', '火把点亮了。', '他转过身来。'], f'{d}/tmp/vo', gap=0.2)
    # place each line at its action time instead of back-to-back
    at = [0.6, 4.8, 7.8, 10.1]
    parts = []
    for i, ((a, b, t), s) in enumerate(zip(cues, at)):
        parts.append(f'[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS,adelay={int(s * 1000)}|{int(s * 1000)}[p{i}]')
    sh([FF, '-y', '-i', vo, '-filter_complex', ';'.join(parts) + ';' + ''.join(f'[p{i}]' for i in range(4)) +
        'amix=inputs=4:normalize=0,apad,atrim=0:12[a]', '-map', '[a]', f'{d}/tmp/vo_timed.wav'])
    audio = zl.mix(f'{d}/tmp/vo_timed.wav', zl.bgm(f'{d}/tmp/bgm.wav', 13, 'warm'), f'{d}/tmp/mix.wav', 12.0)
    ev = [(s, s + (b - a) + 0.4, 'Cap', t) for (a, b, t), s in zip(cues, at)]
    ass = zl.write_ass(f'{d}/tmp/c.ass', LW, LH, ev)
    final = zl.finish(silent, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, [{'source': 'procedural 2D puppet (PIL), hevi-zero/puppets.py caveman_scene'}],
                min_motion=0.4, notes='actions: walk-in 0-4.5s, crouch+pick stone 4.5-7s, light/raise torch 7-10s, turn 10-11s')


def _presenter_video(d, wav, W, H, fps=24, **kw):
    env = zl.rms_envelope(wav, fps)
    mouth = puppets.mouth_series(env)
    p = puppets.Presenter(W, H, **kw)
    return zl.frames_to_video((np.asarray(p.frame(i, float(m), fps)) for i, m in enumerate(mouth)),
                              f'{d}/tmp/presenter.mp4', W, H, fps)


def talking_head():
    line = 'talking_head'; d = work(line)
    L = ['大家好，今天用一分钟讲清楚北京人。', '北京人是生活在周口店一带的直立人，距今大约七十万到二十万年。',
         '他们会打制石器，也留下了用火的痕迹。', '一九二九年发现的头盖骨，让周口店举世闻名。', '我们下期见。']
    vo, cues = zl.tts_lines(L, f'{d}/tmp/vo')
    pv = _presenter_video(d, vo, LW, LH)
    total = dur(vo)
    audio = zl.mix(vo, zl.bgm(f'{d}/tmp/bgm.wav', total + 1, 'warm'), f'{d}/tmp/mix.wav', total, -26)
    ev = caps(cues) + [(0.3, 4.5, 'Lower', r'{\an1\fad(300,300)\fs34}小周 · 历史一分钟')]
    ass = zl.write_ass(f'{d}/tmp/t.ass', LW, LH, ev)
    final = zl.finish(pv, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, [{'source': 'procedural 2D presenter, mouth driven by VO RMS (5 visemes)'}],
                min_motion=0.3, notes='2D cartoon lip-sync from audio amplitude; NOT a photoreal digital human')


def avatar_spokesperson():
    line = 'avatar_spokesperson'; d = work(line)
    L = ['你好，我是社区图书馆的小林。', '这个周末，我们在儿童区举办免费的绘本共读活动。',
         '周六和周日上午十点开始，适合四到八岁的小朋友。', '不需要报名，带上孩子直接来就好。', '我们周末见！']
    vo, cues = zl.tts_lines(L, f'{d}/tmp/vo')
    total = dur(vo) + 0.8
    Q = ['library bookshelves', 'children reading books', 'parent reading to child', 'kids library playing']
    shots, prov = [], []
    seg = total / len(Q) + 0.5
    for i, q in enumerate(Q):
        s = zl.pexels(q, min_d=4); prov.append({k: v for k, v in s.items() if k != 'path'})
        shots.append(zl.shot(s['path'], f'{d}/tmp/s{i}.mp4', seg, LW, LH, move=['push', 'pan_r', 'pull', 'pan_l'][i]))
    film = zl.xfade_concat(shots, f'{d}/tmp/film.mp4', 0.5)
    P = 360
    pv = _presenter_video(d, vo, P, P, bg=((235, 245, 250), (200, 225, 240)), suit=(40, 110, 90), skin=(245, 210, 185),
                          hair=(25, 20, 18), tie=(240, 190, 60), studio=False)
    comp = f'{d}/tmp/comp.mp4'
    sh([FF, '-y', '-i', film, '-i', pv, '-filter_complex',
        f'[1:v]format=rgba,geq=lum=\'p(X,Y)\':a=\'if(lte(hypot(X-{P / 2},Y-{P / 2}),{P / 2 - 4}),255,0)\'[c];'
        f'[0:v][c]overlay=W-w-50:H-h-120:shortest=1,format=yuv420p[v]', '-map', '[v]', '-c:v', 'libx264',
        '-preset', 'veryfast', '-crf', '20', comp])
    audio = zl.mix(vo, zl.bgm(f'{d}/tmp/bgm.wav', total + 1, 'bright'), f'{d}/tmp/mix.wav', total, -22)
    ev = [(a, b, 'Cap', r'{\an1\pos(70,%d)}' % (LH - 70) + t) for a, b, t in cues]
    ev += [(0.3, total - 3, 'Lower', r'{\an7\pos(70,60)\fs34}社区图书馆 · 周末绘本共读'),
           (total - 3, total, 'Title', r'{\fad(300,0)\fs64}周六 / 周日 10:00 · 免费')]
    ass = zl.write_ass(f'{d}/tmp/a.ass', LW, LH, ev)
    final = zl.finish(comp, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, prov + [{'source': 'procedural 2D presenter PiP, RMS lip-sync'}],
                notes='spokesperson layout: stock b-roll + circular avatar PiP + lower third + CTA end card')


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
    return wins


def shorts_clip():
    line = 'shorts_clip'; d = work(line)
    src = f'{SEED}/nasa_KSC-20190716-MH-NAS01_0001-Return_to_the.mp4'
    segs = _whisper(src, 'en')
    json.dump(segs, open(f'{d}/transcript.json', 'w'), ensure_ascii=False, indent=1)
    W, H = 720, 1280
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
        ev.append((0, b - a, 'Kicker', r'{\an8\pos(%d,140)\fs38}MICHAEL COLLINS · APOLLO 11' % (W // 2)))
        ass = zl.write_ass(f'{d}/tmp/c{k}.ass', W, H, ev)
        out = f'{d}/{line}_{k + 1:02d}.mp4'
        sh([FF, '-y', '-ss', f'{a:.2f}', '-t', f'{b - a:.2f}', '-i', src, '-filter_complex',
            f'[0:v]split[bg][fg];[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3,eq=brightness=-0.15[b];'
            f'[fg]scale={W}:-2:flags=lanczos,unsharp=5:5:0.6[f];[b][f]overlay=0:(H-h)/2-80,'
            f"subtitles='{d}/tmp/c{k}.ass':fontsdir=/usr/share/fonts/opentype/noto[v]",
            '-map', '[v]', '-map', '0:a', '-af', 'loudnorm=I=-15', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
            '-c:a', 'aac', '-movflags', '+faststart', out])
        outs.append(out)
    recs = [zl.qa(o) for o in outs]
    zl.contact_sheet(outs[0], f'{d}/contact_sheet.jpg')
    rec = {'line': line, 'finals': outs, 'qa': recs, 'cost_usd': 0, 'pass': all(r['pass'] for r in recs),
           'provenance': [{'source': 'NASA public domain: Return to the Pad (KSC-20190716-MH-NAS01_0001)', 'path': src},
                          {'source': 'faster-whisper base (local CPU) word timestamps'}]}
    json.dump(rec, open(f'{d}/record.json', 'w'), ensure_ascii=False, indent=2)
    shutil.rmtree(f'{d}/tmp', ignore_errors=True)
    print(line, 'PASS' if rec['pass'] else 'FAIL', [r['checks'] for r in recs])
    return rec


def podcast_repurpose():
    line = 'podcast_repurpose'; d = work(line)
    src = f'{SEED}/nasa_Apollo_14_Launch_Coverage.mp4'
    segs = _whisper(src, 'en')
    json.dump(segs, open(f'{d}/transcript.json', 'w'), ensure_ascii=False, indent=1)
    (i, j), = _pick_windows(segs, 1, (35, 55))
    a, b = segs[i]['start'] - 0.2, segs[j]['end'] + 0.3
    W, H = 1080, 1080
    ev = [(s['start'] - a, s['end'] - a, 'Cap', r'{\an5\pos(%d,%d)\fs40}' % (W // 2, int(H * 0.80)) + s['text']) for s in segs[i:j + 1]]
    ev += [(0, b - a, 'Kicker', r'{\an7\pos(330,150)\fs30\c&H00C8FF&}SPACE ARCHIVE PODCAST · EP.14'),
           (0, b - a, 'Title', r'{\an7\pos(330,200)\fs52}Apollo 14: the final countdown'),
           (0, b - a, 'Kicker', r'{\an7\pos(330,275)\fs26\c&HCCCCCC&}NASA launch coverage, 31 Jan 1971')]
    ass = zl.write_ass(f'{d}/tmp/p.ass', W, H, ev)
    out = f'{d}/{line}.mp4'
    sh([FF, '-y', '-ss', f'{a:.2f}', '-t', f'{b - a:.2f}', '-i', src, '-filter_complex',
        f'color=c=0x101820:s={W}x{H}:r=30[bgc];'
        f'[0:v]scale=240:240:force_original_aspect_ratio=increase,crop=240:240[cov];'
        f'[0:a]asplit[a1][a2];[a1]showwaves=s={W - 160}x260:mode=cline:colors=0x00C8FF|0x0088CC:rate=30,format=rgba[w];'
        f'[bgc][cov]overlay=60:120[t1];[t1][w]overlay=80:470:shortest=1,'
        f"drawbox=x=60:y=ih-60:w='(iw-120)*t/{b - a:.2f}':h=8:color=0x00C8FF:t=fill,"
        f"subtitles='{ass}':fontsdir=/usr/share/fonts/opentype/noto[v]",
        '-map', '[v]', '-map', '[a2]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-c:a', 'aac',
        '-movflags', '+faststart', out])
    return save(d, line, out, [{'source': 'NASA public domain: Apollo 14 Launch Coverage', 'path': src},
                               {'source': 'faster-whisper base (local CPU)'}], min_motion=0.5,
                allow_dark=True, notes='audiogram format: cover art + live waveform + captions + progress bar, distinct from shorts_clip')


def reference_adapt():
    line = 'reference_adapt'; d = work(line)
    ref = f'{SEED}/nasa_Earth_Views_from_the_International_Space.mp4'
    # adaptation: different structure (night->day->storm->limb), Chinese narration, new pacing, grade, captions
    plan = [(18, '地球的弧线上，云层在海面上铺开。'), (82, '荒漠和海岸线，从脚下缓缓经过。'),
            (139, '机械臂伸出去，捕获一艘货运飞船。'), (164, '日出只用几秒钟，就点亮了整条地平线。'),
            (174, '那条蓝色的细线，就是保护我们的大气层。')]
    vo, cues = zl.tts_lines([p[1] for p in plan], f'{d}/tmp/vo')
    total = dur(vo) + 1.0
    shots = []
    for k, ((a, b, _), (ss, _)) in enumerate(zip(cues, plan)):
        seg = (b - a) + 0.35 + (0.6 if k else 0) + (1.0 if k == len(plan) - 1 else 0)
        shots.append(zl.shot(ref, f'{d}/tmp/s{k}.mp4', seg, LW, LH, ss=ss, move=['push', 'pan_r', 'pull', 'pan_l', 'push'][k],
                             grade='scale=iw:ih:flags=lanczos,unsharp=5:5:0.8,eq=contrast=1.08:saturation=1.2'))
    film = zl.xfade_concat(shots, f'{d}/tmp/film.mp4', 0.6, 'circleopen')
    ev = caps(cues) + [(0.2, 3.0, 'Title', r'{\fad(300,300)}从轨道看家园')]
    ass = zl.write_ass(f'{d}/tmp/r.ass', LW, LH, ev)
    audio = zl.mix(vo, zl.bgm(f'{d}/tmp/bgm.wav', total + 1, 'warm'), f'{d}/tmp/mix.wav', total)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass)
    rec = save(d, line, final, [{'source': 'reference: NASA Earth Views from the ISS (public domain)', 'path': ref,
                                 'segments_used_s': [p[0] for p in plan]}],
               allow_dark=True, notes='reordered 4 segments, new zh narration, grade, camera moves, transitions, captions; source is 320x180 so output is soft')
    return rec


LINES = {f.__name__: f for f in [kinetic_promo, explainer, cinematic, director_pipeline, history_scene,
                                 character_animation, talking_head, avatar_spokesperson, shorts_clip,
                                 podcast_repurpose, reference_adapt]}

if __name__ == '__main__':
    todo = list(LINES) if sys.argv[1:] == ['all'] else sys.argv[1:]
    res = {}
    for n in todo:
        t = time.time()
        try:
            r = LINES[n]()
            res[n] = {'pass': r.get('pass') if 'pass' in r else r['qa']['pass'], 'secs': round(time.time() - t)}
        except Exception as e:  # keep going; record the failure honestly
            res[n] = {'error': str(e)[-600:], 'secs': round(time.time() - t)}
            print(n, 'ERROR', str(e)[-600:])
    os.makedirs(OUT, exist_ok=True)
    json.dump(res, open(f'{OUT}/run_{int(time.time())}.json', 'w'), ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False))
