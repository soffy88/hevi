"""常驻 Piper 合成进程（在装了 piper-tts 的 venv 里跑）：stdin 每行 JSON {text,out}，合成后回一行 ok/err。"""
import json, sys, wave
from piper import PiperVoice

voice = PiperVoice.load(sys.argv[1])
print("ready", flush=True)
for line in sys.stdin:
    try:
        job = json.loads(line)
        with wave.open(job["out"], "wb") as w:
            voice.synthesize_wav(job["text"], w)
        print("ok", flush=True)
    except Exception as e:  # noqa: BLE001
        print("err " + str(e).replace("\n", " ")[:200], flush=True)
