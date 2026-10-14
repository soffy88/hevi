"""Generate the Xiaoya voice-cache library: ~150 common host lines → 24 kHz
mono wavs (CosyVoice3 zero-shot, same female voice as the reading feature),
then embed the text with EmbeddingGemma 2 and write manifest.json + index.npz.

Run with the CosyVoice venv (it is NOT pip-installed; imported via sys.path):

    TMPDIR=/data/soffy/voicecache/tmp \\
    /data/soffy/cosyvoice/venv/bin/python \\
        hevi/live_host/voicecache/gen_voicecache.py [--root /data/soffy/voicecache]

Idempotent: existing wavs are skipped, so it can be re-run after a crash.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

# ---- paths ----
ROOT = Path(os.environ.get("HEVI_VOICECACHE_ROOT", "/data/soffy/voicecache"))
COSY_DIR = "/data/soffy/cosyvoice/CosyVoice"
MODEL_DIR = "/data/soffy/cosyvoice/models/Fun-CosyVoice3-0.5B"
PROMPT_WAV = "./asset/zero_shot_prompt.wav"
PROMPT_TEXT = "You are a helpful assistant.<|endofprompt|>希望你以后能够做的比我还好呦。"
WAV_DIR = ROOT / "wav"


# --------------------------------------------------------------------------
# the library text — ~150 lines in Xiaoya's persona voice
# (persona = hevi/live_host/oprim/llm_ollama.py SYSTEM_PROMPT; rule 7 = no
# selling/prices/coupons/links; digits written as Chinese words)
# --------------------------------------------------------------------------

CATEGORIES: dict[str, dict] = {
    "greeting": {
        "motion": "g_wave",
        "lines": [
            "欢迎来到小雅的直播间，很高兴见到大家",
            "欢迎新进来的朋友，小雅等你好久了",
            "刚进来的宝子们点点关注，别迷路啦",
            "大家好呀，今天也要开开心心的",
            "又见到你们啦，小雅心里暖暖的",
            "欢迎回来呀，今天想聊点啥",
            "新来的朋友打个招呼嘛，小雅看得到你哦",
            "欢迎光临小雅的房间，随便坐呀",
            "大家晚上好，今天也辛苦啦",
            "哈喽哈喽，小雅来啦",
        ],
    },
    "gift_thanks": {
        "motion": "g_heart",
        "lines": [
            "谢谢哥哥的礼物，小雅收到啦",
            "感谢老板的投喂，比心比心",
            "哇，谢谢这个大礼物，小雅超开心的",
            "谢谢你的小心心，小雅记在心里啦",
            "感谢宝宝的礼物，爱你哟",
            "谢谢大哥送的礼物，小雅给你比个心",
            "又收礼物啦，谢谢大家这么宠我",
            "谢谢这个火箭，大哥太阔气啦",
            "收到礼物小雅就开心，谢谢大家",
            "谢谢宝子的心意，小雅抱抱你",
        ],
    },
    "follow_thanks": {
        "motion": "g_nod",
        "lines": [
            "感谢关注呀，记得常来玩哦",
            "谢谢新关注的宝子，小雅抱抱你",
            "欢迎点关注，以后就是一家人啦",
            "谢谢关注，小雅会经常开播陪你的",
            "新粉丝来啦，小雅给你比个心",
            "谢谢关注，关注不迷路哦",
            "感谢点亮小关小注，爱你么么哒",
        ],
    },
    "like_thanks": {
        "motion": "g_nod",
        "lines": [
            "谢谢大家的赞，小雅看到啦",
            "感谢点赞，你们最贴心了",
            "点赞的宝子运气都超好哦",
            "谢谢哥哥的小赞赞",
            "这么多赞，小雅脸都红啦",
            "谢谢点赞，大家也给自己点个赞吧",
        ],
    },
    "top_fan_thanks": {
        "motion": "g_both",
        "lines": [
            "谢谢榜一大哥，大哥威武",
            "感谢榜一大哥一直以来的支持",
            "榜一大哥到啦，小雅给你深深鞠个躬",
            "谢谢大哥，今天又是被宠爱的一天",
            "大哥最棒了，小雅爱死你啦",
            "榜一大哥来了，全场最靓的仔就是你",
            "谢谢榜一大哥的守护，小雅记一辈子",
        ],
    },
    "refusal": {
        "motion": "talk_a",
        "lines": [
            "小雅不能加微信哦，大家在这里聊就好啦",
            "我们这里不卖东西的，放心看就好",
            "小雅是免费的，不收钱不收费哦",
            "不能发链接的呀，平台会管的",
            "小雅不知道哪里买，你问问官方客服吧",
            "这里不方便留联系方式哦，理解一下",
            "小雅只陪大家聊天，不代购不卖货",
            "小雅不卖货哦，不过你想要什么功能的手机呀",
            "家人们别急呀，咱们直播间没有官方链接哦",
            "小雅不能查别人的号码哦，这会侵犯隐私呢",
            "这里不报价的，小雅只陪大家聊聊天",
        ],
    },
    "ai_disclosure": {
        "motion": "talk_b",
        "lines": [
            "小雅是人工智能生成的数字人哦，让大家见笑啦",
            "我是AI生成的数字人小雅，很高兴认识你",
            "小雅是数字人主播，由人工智能驱动，请多关照",
            "温馨提示，我是AI生成的数字人，不是真人也",
            "我是生成的数字人主播哦，不过有真人在后台值守呢",
        ],
    },
    "goodbye": {
        "motion": "g_wave",
        "lines": [
            "时间不早啦，大家早点休息，晚安",
            "今天先下播咯，明天同一时间不见不散",
            "拜拜啦，明天小雅还在这里等你",
            "要下播啦，谢谢今天的陪伴，么么哒",
            "晚安晚安，做个好梦哦",
            "今天就到这里啦，大家注意身体呀",
            "小雅要去休息啦，明天接着聊",
            "舍不得大家，但是要下播啦，明天见",
        ],
    },
    "idle_chatter": {
        "motion": "idle",
        "lines": [
            "有没有人陪小雅聊聊天呀",
            "今天天气真好，大家出门走走啦",
            "大家吃了吗，小雅刚吃完饭",
            "好无聊呀，有人讲个笑话嘛",
            "今天过得怎么样，跟小雅说说呗",
            "想听歌吗，小雅给你们哼两句",
            "周末啦，大家都去哪里玩了呀",
            "有没有人分享一下今天开心的事",
            "小雅一个人好孤单，谁来陪我呀",
            "今天想聊点啥，你们说了算",
        ],
    },
    "comfort": {
        "motion": "g_lean",
        "lines": [
            "别难过啦，都会好起来的",
            "累了就休息一下，别硬撑哦",
            "加油，你一定可以的，小雅相信你",
            "抱抱你，有什么委屈跟小雅说",
            "不开心的时候就来找小雅，我一直都在",
            "你已经很棒啦，别对自己太严格",
            "今天也辛苦了，给自己一点奖励吧",
            "没事的不开心都会过去的，小雅陪你",
        ],
    },
    "ask_back": {
        "motion": "talk_a",
        "lines": [
            "你平时喜欢看什么类型的直播呀",
            "你今天过得怎么样呀",
            "你最喜欢什么颜色呀",
            "你那边是冬天吗，冷不冷呀",
            "你养宠物吗，小雅可喜欢猫猫狗狗啦",
            "你有什么开心事想跟小雅分享吗",
            "你平时几点看直播呀",
            "你最喜欢哪首诗呀",
        ],
    },
    # --- second batch: broader paraphrase coverage for the retrieval index ---
    # The live reply is paraphrased by the LLM, so the cache needs many surface
    # forms per intent for cosine lookup to fire.  Same style rules: no digits
    # (write numbers as Chinese words), no selling/prices/links (rule 7).
    "greeting_extra": {
        "motion": "g_wave",
        "lines": [
            "来啦来啦，欢迎欢迎",
            "嗨，欢迎来到小雅的直播间",
            "欢迎宝子们，快进来坐",
            "哟，新朋友来了，欢迎欢迎",
            "大家早上好呀，今天也要加油",
            "下午好呀，小雅等你们好久了",
            "终于见到大家了，好开心",
            "欢迎每一位进来的朋友",
        ],
    },
    "gift_thanks_extra": {
        "motion": "g_heart",
        "lines": [
            "谢谢宝子的礼物呀",
            "感谢感谢，小雅太开心啦",
            "礼物收到，谢谢大哥",
            "哇塞，这个礼物太贵重了，谢谢",
            "小雅收到你的心意啦，谢谢",
            "谢谢你的打赏，小雅爱你们",
            "又收到礼物了，开心到转圈圈",
        ],
    },
    "follow_thanks_extra": {
        "motion": "g_nod",
        "lines": [
            "感谢支持，小雅谢谢你了",
            "关注小雅的宝子最好了",
            "谢谢你的关注，小雅记住了",
            "感谢老铁关注，么么哒",
            "谢谢你关注小雅，常来看我哦",
        ],
    },
    "like_thanks_extra": {
        "motion": "g_nod",
        "lines": [
            "谢谢大家的双击点赞",
            "赞都收到啦，谢谢你们",
            "感谢每一个赞，爱你们哟",
            "谢谢点赞，小雅动力满满",
        ],
    },
    "top_fan_thanks_extra": {
        "motion": "g_both",
        "lines": [
            "谢谢榜一哥哥一直陪着我",
            "大哥的每份支持小雅都记着",
            "感谢榜一大哥，小雅给你敬个礼",
            "有大哥在，小雅特别安心",
            "大哥太给力了，谢谢谢谢",
        ],
    },
    "refusal_extra": {
        "motion": "talk_a",
        "lines": [
            "小雅这里不能加好友哦",
            "不好意思，小雅不卖东西呀",
            "小雅只聊天，不谈钱哦",
            "没办法发链接，大家理解一下",
            "这个价格小雅真不知道呢",
            "小雅不能留电话哦，平台不允许",
            "私事小雅不方便说，咱们聊点开心的",
            "小雅只陪聊，别的不做哦",
            "买东西找官方渠道哦，小雅不参与",
            "这个问题小雅答不上来，换个话题吧",
        ],
    },
    "goodbye_extra": {
        "motion": "g_wave",
        "lines": [
            "太晚啦，大家快去睡觉",
            "小雅下播啦，明天见哦",
            "今天就到这，拜拜拜拜",
            "要去休息了，你们也早点睡",
            "我们下次再见，想你们哟",
            "先撤啦，大家晚安好梦",
            "谢谢陪伴，我们明天继续聊",
        ],
    },
    "idle_chatter_extra": {
        "motion": "idle",
        "lines": [
            "有人在吗，出来聊会儿天呀",
            "今天有点困，但是小雅还在",
            "你们那边下雨了吗",
            "小雅刚追完一部剧，好看好看",
            "突然想吃火锅了，有人请吗",
            "大家平时都几点睡呀",
            "刚运动完，整个人都精神了",
            "有没有好听的歌推荐一下",
        ],
    },
    "comfort_extra": {
        "motion": "g_lean",
        "lines": [
            "抱抱你，慢慢会好的",
            "别哭啦，小雅陪着你呀",
            "再坚持一下，你很厉害了",
            "今天不顺，明天会顺的哦",
            "难过就哭出来，别憋着",
            "你已经很努力了，歇一歇吧",
        ],
    },
    "ask_back_extra": {
        "motion": "talk_a",
        "lines": [
            "你喜欢哪个城市呀",
            "周末一般都做什么呀",
            "你喜欢画画还是唱歌呀",
            "最近有看什么好看的剧吗",
            "你是学生还是上班族呀",
            "你吃过最难忘的东西是什么",
            "如果能去旅行，你想去哪里",
            "你喜欢猫还是喜欢狗呀",
        ],
    },
}


def _slug(text: str) -> str:
    import re

    s = re.sub(r"[^\w一-鿿]+", "_", text)
    return s[:32]


def build_plan() -> list[dict]:
    plan = []
    for cat, meta in CATEGORIES.items():
        for i, line in enumerate(meta["lines"]):
            plan.append(
                {
                    "id": f"{cat}_{i:02d}",
                    "text": line,
                    "category": cat,
                    "motion": meta["motion"],
                }
            )
    return plan


# --------------------------------------------------------------------------
# generation
# --------------------------------------------------------------------------


def load_model():
    os.chdir(COSY_DIR)
    sys.path += [".", "third_party/Matcha-TTS"]
    import torch
    import torchaudio

    torch.set_num_threads(int(os.environ.get("HEVI_LIVE_THREADS", "8")))
    from cosyvoice.cli.cosyvoice import AutoModel

    m = AutoModel(model_dir=MODEL_DIR)
    return m, torch, torchaudio


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--skip-gen", action="store_true", help="only (re)build index + manifest")
    args = ap.parse_args()
    root = Path(args.root)
    wav_dir = root / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)

    plan = build_plan()
    print(f"plan: {len(plan)} lines across {len(CATEGORIES)} categories", flush=True)

    model = None
    total_audio = 0.0
    for item in plan:
        out = wav_dir / f"{item['id']}.wav"
        item["wav"] = f"wav/{item['id']}.wav"
        if out.exists() and out.stat().st_size > 0:
            item["duration"] = _duration(out)
            continue
        if args.skip_gen:
            continue
        if model is None:
            model, torch, torchaudio = load_model()
        t0 = time.time()
        w = torch.cat(
            [
                j["tts_speech"]
                for j in model.inference_zero_shot(
                    item["text"], PROMPT_TEXT, PROMPT_WAV, stream=False
                )
            ],
            1,
        )
        torchaudio.save(str(out), w, model.sample_rate)
        dur = w.shape[1] / model.sample_rate
        item["duration"] = round(float(dur), 2)
        total_audio += dur
        print(
            f"{item['id']} dur={dur:.2f}s gen={time.time() - t0:.1f}s rtf={(time.time() - t0) / max(dur, 1e-3):.2f}",
            flush=True,
        )

    # ---- index via EG2 (offline only; does NOT touch the live path) ----
    _build_index(plan, root)
    _write_manifest(plan, root)
    print(f"TOTAL audio_seconds={total_audio:.1f} TTS DONE", flush=True)


def _duration(wav_path: Path) -> float:
    try:
        import soundfile as sf

        return round(float(sf.info(str(wav_path)).frames / sf.info(str(wav_path)).samplerate), 2)
    except Exception:
        return 0.0


def _build_index(plan: list[dict], root: Path) -> None:
    """Embed every line's text with EG2 and save index.npz.  Uses the shared
    service if reachable, else the local CPU fallback.  Never blocks the live
    path (offline build step)."""
    try:
        from hevi.live_host.avatar.motionrag import Config, get_embedder, DIM
    except Exception as e:
        print("skip index (no motionrag embedder):", e, flush=True)
        return
    cfg = Config()
    try:
        emb = get_embedder(cfg, allow_audio=False)
    except Exception as e:
        print("skip index (embedder unavailable):", e, flush=True)
        return
    texts = [p["text"] for p in plan]
    vecs = emb.text(texts, query=False)  # Document vectors for the library
    ids = np.array([p["id"] for p in plan])
    np.savez_compressed(root / "index.npz", ids=ids, text=vecs)
    print(f"index.npz written: {vecs.shape}", flush=True)


def _write_manifest(plan: list[dict], root: Path) -> None:
    # drop any entries whose wav did not get generated
    entries = [
        p for p in plan if (root / p["wav"]).exists() and (root / p["wav"]).stat().st_size > 0
    ]
    manifest = {
        "voice": "Xiaoya (小雅) — female host, CosyVoice3 zero-shot",
        "model_dir": MODEL_DIR,
        "prompt_wav": PROMPT_WAV,
        "sample_rate": 24000,
        "channels": 1,
        "dim": 768,
        "n_entries": len(entries),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "entries": [
            {
                "id": e["id"],
                "text": e["text"],
                "wav": e["wav"],
                "duration": e.get("duration", 0.0),
                "motion": e["motion"],
                "category": e["category"],
            }
            for e in entries
        ],
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"manifest.json written: {len(entries)} entries", flush=True)


if __name__ == "__main__":
    main()
