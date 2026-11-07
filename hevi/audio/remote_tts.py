import urllib.request
import json

def synthesize_remote_tts(text: str, host: str = "100.119.113.90", port: int = 8795, voice: str = "auto") -> bytes:
    url = f"http://{host}:{port}/tts"
    payload = json.dumps({"text": text, "voice": voice}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()
