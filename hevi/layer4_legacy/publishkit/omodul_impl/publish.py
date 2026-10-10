import json
import hashlib
import subprocess
import time
import shutil
import re
from pathlib import Path
from typing import Any, Dict

from oprim.llm.llm_call import llm_call
from oprim.errors import LLMError

def build_publish_bundle(video_path: Path, script_path: Path, output_dir: Path, config: Dict[str, Any] = None) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = video_path.resolve()
    script_path = script_path.resolve()
    
    script_content = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
    
    llm_degraded = False
    fact_sources = {"sources": [], "status": "ok"}
    copy_md = ""
    
    # 1. QA
    qa_report = run_qa(video_path)
    
    # 2. Fact sources & Copy (LLM)
    prompt = f"请根据以下文稿，提取事实来源列表（以JSON返回：{{\"sources\": [\"来源1\"]}}），并根据短视频发布文案要求生成抖音、小红书、B站等平台的文案。\n文稿：\n{script_content}"
    try:
        resp = llm_call(prompt, provider="qwen3_dashscope", temperature=0.3)
        res_text = resp.text
        # Naive parse
        if "{" in res_text and "}" in res_text:
            try:
                json_part = res_text[res_text.find("{"):res_text.rfind("}")+1]
                fact_sources = json.loads(json_part)
            except:
                pass
        copy_md = res_text
    except Exception as e:
        llm_degraded = True
        fact_sources = {"sources": ["规则降级，未能提取提取事实来源"], "status": "degraded"}
        copy_md = f"# 抖音\n标题：规则降级，未能生成文案\n正文：{script_content[:100]}...\n（共用免责段）"
    
    qa_report["llm_degraded"] = llm_degraded
    
    # 3. Cover Generation (extract mid frame)
    cover_path = output_dir / "cover.jpg"
    try:
        subprocess.run(["/home/soffy/.local/bin/ffmpeg", "-y", "-i", str(video_path), "-ss", "00:00:02", "-vframes", "1", str(cover_path)], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        pass
    
    # Write outputs
    (output_dir / "fact_sources.json").write_text(json.dumps(fact_sources, ensure_ascii=False, indent=2))
    (output_dir / "qa_report.json").write_text(json.dumps(qa_report, ensure_ascii=False, indent=2))
    (output_dir / "copy.md").write_text(copy_md, encoding="utf-8")
    
    return {
        "cover_path": str(cover_path),
        "copy_path": str(output_dir / "copy.md"),
        "qa_report_path": str(output_dir / "qa_report.json"),
        "fact_sources_path": str(output_dir / "fact_sources.json"),
        "llm_degraded": llm_degraded
    }

def run_qa(video_path: Path) -> dict:
    qa = {}
    try:
        p = json.loads(subprocess.check_output(['/home/soffy/.local/bin/ffprobe','-v','error','-show_streams','-show_format','-of','json',str(video_path)]))
        v = [s for s in p['streams'] if s['codec_type']=='video'][0]
        a = [s for s in p['streams'] if s['codec_type']=='audio'][0]
        qa['分辨率'] = f"{v.get('width',0)}x{v.get('height',0)}"
        qa['视频帧数'] = int(v.get('nb_frames', 0))
        qa['时长'] = round(float(p['format'].get('duration', 0)),2)
        qa['体积MB'] = round(int(p['format'].get('size', 0))/1048576, 1)
        
        # Audio check
        r = subprocess.run(['/home/soffy/.local/bin/ffmpeg','-nostdin','-v','info','-i',str(video_path),'-vf','blackdetect=d=0.3:pix_th=0.06','-af','silencedetect=n=-45dB:d=1.5','-f','null','-'],capture_output=True,text=True)
        qa['黑帧段'] = [l.split('] ')[-1] for l in r.stderr.split('\n') if 'black_start' in l] or '无'
        qa['长静音段'] = [l.split('] ')[-1] for l in r.stderr.split('\n') if 'silence_start' in l] or '无'
        qa['解码错误'] = [l for l in r.stderr.split('\n') if 'error' in l.lower()][:5] or '无'
        
        qa['sha256'] = hashlib.sha256(video_path.read_bytes()).hexdigest()
    except Exception as e:
        qa['error'] = str(e)
    return qa
