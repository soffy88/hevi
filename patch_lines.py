import sys

def patch(filename):
    with open(filename, 'r') as f:
        content = f.read()

    lines = content.split('\n')
    idx = 0
    for i, line in enumerate(lines):
        if line.startswith('LINES = {'):
            idx = i
            break
            
    insert = """
def _documentary_montage(output_dir: str = OUT):
    line = 'documentary_montage'; d = str(output_dir) if output_dir != OUT else work(line)
    import os
    os.makedirs(d + "/tmp", exist_ok=True)
    L = ['1971年1月31日，阿波罗14号发射。', '这是人类探索太空的又一重要时刻。']
    vo, cues = zl.tts_lines(L, f'{d}/tmp/vo')
    total = dur(vo) + 1.0
    s = zl.pexels('rocket launch', min_d=total)
    prov = [{k: v for k, v in s.items() if k != 'path'}]
    film = zl.shot(s['path'], f'{d}/tmp/film.mp4', total, LW, LH)
    ev = caps(cues)
    ass = zl.write_ass(f'{d}/tmp/d.ass', LW, LH, ev)
    audio = zl.mix(vo, zl.bgm(f'{d}/tmp/bgm.wav', total + 1, 'epic'), f'{d}/tmp/mix.wav', total)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, prov, allow_dark=True)

def _localization_dub(output_dir: str = OUT):
    line = 'localization_dub'; d = str(output_dir) if output_dir != OUT else work(line)
    import os
    os.makedirs(d + "/tmp", exist_ok=True)
    L = ['这是外语配音版本。', '我们将原声替换为了本地语言。']
    vo, cues = zl.tts_lines(L, f'{d}/tmp/vo')
    total = dur(vo) + 1.0
    s = zl.pexels('people talking', min_d=total)
    prov = [{'source': 'localization_dub mock'}]
    film = zl.shot(s['path'], f'{d}/tmp/film.mp4', total, LW, LH)
    ev = caps(cues)
    ass = zl.write_ass(f'{d}/tmp/d.ass', LW, LH, ev)
    audio = zl.mix(vo, zl.bgm(f'{d}/tmp/bgm.wav', total + 1, 'warm'), f'{d}/tmp/mix.wav', total)
    final = zl.finish(film, audio, f'{d}/{line}.mp4', ass)
    return save(d, line, final, prov, allow_dark=True)
"""
    lines.insert(idx, insert)
    with open(filename, 'w') as f:
        f.write('\n'.join(lines))

if __name__ == '__main__':
    patch('hevi/layer4_legacy/omlines/omodul_impl/lines.py')
