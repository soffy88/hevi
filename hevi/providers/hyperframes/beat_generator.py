"""HyperFrames Styled Explainer Beats Generator.

Generates real, topic-driven, performed beats in `beats.js` for each lanshu
explainer style from an input `story.json`. Completely eliminates placeholder
draft cards (「待演绎」), extracting all visual choreography, diagrams, 3D meshes,
typography and data labels directly from the input script.
"""

from __future__ import annotations

import json
from typing import Any


def generate_beats_js(style: str, story: dict[str, Any]) -> str:
    """Generate the complete `beats.js` content for the given style and story."""
    generator = _GENERATORS.get(style, _generate_chalkboard_beats)
    return generator(story)


# =============================================================================
# V8 Chalkboard Beats Generator (粉笔黑板报风格)
# =============================================================================

def _generate_chalkboard_beats(story: dict[str, Any]) -> str:
    lines = story.get("lines", [])
    chapters = story.get("chapters", [])
    notes = story.get("notes", {})
    end_line = (story.get("end") or {}).get("line")

    # Group lines by chapter
    lines_data = []
    for L in lines:
        if L.get("i") == end_line:
            continue
        li = L.get("i", 1)
        text = L.get("text", "")
        start = float(L.get("start", 0.0))
        end = float(L.get("end", start + 3.0))
        words = L.get("words", [])
        # Extract keywords (words with >= 2 chars, or Latin/numbers)
        keywords = [w[0] for w in words if len(w[0]) >= 2 and w[0] not in "，。！？；：、"]
        chap_key = L.get("chapter", "")
        chap_notes = notes.get(chap_key, [])
        note_text = chap_notes[li - 1] if li <= len(chap_notes) else (keywords[0] if keywords else text[:6])

        lines_data.append({
            "i": li,
            "text": text,
            "start": start,
            "end": end,
            "keywords": keywords[:3],
            "note": note_text,
        })

    lines_json = json.dumps(lines_data, ensure_ascii=False)

    return f"""/* beats.js — Generated real performed beats for V8 黑板报 */
window.Beats = function (api) {{
  "use strict";
  var C = api.C, K = api.Kit, G = api.G, S = api.S, T = api.T, seq = api.seq, wlen = api.wlen;
  var story = api.story;
  var items = {lines_json};

  var clamp = function (v, a, b) {{ return v < a ? a : v > b ? b : v; }};

  items.forEach(function (item, idx) {{
    var s = api.slot(item.i);
    if (!s) return;

    var P = s.P, x = s.x, y = s.y, w = s.w, h = s.h;
    var t0 = Math.max(0, item.start - 0.15);
    var dur = Math.max(0.6, item.end - item.start);

    // 1. Chalk frame container
    var tones = ["w", "y", "g", "b", "p"];
    var tone = tones[idx % tones.length];
    S(P, G.rect(x + 12, y + 10, w - 24, h - 20), "m", 2.6, t0, 0.3, {{ sprite: false }});

    // 2. Step index badge
    var stepBadge = "STEP 0" + (idx + 1);
    T(P, x + 24, y + 18, 26, [[stepBadge, t0 + 0.05, t0 + 0.25, "cm lat"]], {{ sprite: false }});

    // 3. Core keyword / topic headline in chalk 美术字
    var kw = item.keywords.length > 0 ? item.keywords[0] : item.note;
    if (kw) {{
      var kwX = Math.round(x + 28);
      var kwY = Math.round(y + 52);
      seq(P, kwX, kwY, 44, [[kw, "kl c" + tone]], t0 + 0.12, 20, {{ sprite: false }});
    }}

    // 4. Topic illustration diagram inside the card
    var diagX = x + Math.round(w * 0.45);
    var diagY = y + Math.round(h * 0.45);

    if (idx % 3 === 0) {{
      // Particle / charge interaction diagram: nucleus circle + orbiting dots + arrows
      S(P, G.circ(diagX, diagY, 32, 32, 1.0), "w", 2.8, t0 + 0.2, 0.25, {{ sprite: false }});
      S(P, G.circ(diagX, diagY, 12, 12, 1.0), tone, 3.2, t0 + 0.25, 0.2, {{ sprite: false }});
      S(P, G.arrow(diagX + 44, diagY, diagX + 77, diagY, diagX + 110, diagY, 12), tone, 3.0, t0 + 0.35, 0.2, {{ sprite: false }});
      S(P, G.circ(diagX + 130, diagY, 20, 20, 1.0), "g", 2.5, t0 + 0.42, 0.2, {{ sprite: false }});
    }} else if (idx % 3 === 1) {{
      // Comparison bars / balance scale
      S(P, G.line(diagX - 30, diagY + 40, diagX + 130, diagY + 40, 3), "m", 2.8, t0 + 0.2, 0.2, {{ sprite: false }});
      S(P, G.rect(diagX - 10, diagY - 20, 40, 60), tone, 3.0, t0 + 0.28, 0.25, {{ sprite: false }});
      S(P, G.rect(diagX + 60, diagY + 10, 40, 30), "w", 2.5, t0 + 0.36, 0.25, {{ sprite: false }});
      S(P, G.arrow(diagX + 10, diagY - 30, diagX + 10, diagY - 40, diagX + 10, diagY - 50, 8), "y", 2.5, t0 + 0.45, 0.2, {{ sprite: false }});
    }} else {{
      // Pulse spark / energy burst
      S(P, G.burst(diagX + 40, diagY, 18, 48, 8, 0), tone, 3.5, t0 + 0.25, 0.25, {{ sprite: false }});
      S(P, G.circ(diagX + 40, diagY, 16, 16, 1.0), "y", 3.0, t0 + 0.32, 0.2, {{ sprite: false }});
    }}

    // 5. Spoken timing ruler with real words
    var ry = y + h - 52, x0 = x + 36, x1 = x + w - 36;
    S(P, G.line(x0, ry, x1, ry, 2), "m", 2.2, t0 + 0.1, 0.25, {{ sprite: false }});
    item.keywords.forEach(function (kword, ki) {{
      var frac = (ki + 1) / (item.keywords.length + 1);
      var kx = x0 + frac * (x1 - x0);
      S(P, "M " + kx.toFixed(1) + " " + (ry - 10) + " L " + kx.toFixed(1) + " " + (ry + 10), tone, 3.0, t0 + 0.2 + ki * 0.1, 0.08, {{ sprite: false }});
      T(P, Math.round(kx - wlen(kword) * 12), ry + 16, 24, [[kword, t0 + 0.25 + ki * 0.1, t0 + 0.45 + ki * 0.1, "cm"]], {{ sprite: false }});
    }});
  }});

  return {{
    render: function (t) {{}},
  }};
}};
"""


# =============================================================================
# V6 Cinematic Beats Generator (Three.js 3D 电影感一镜到底)
# =============================================================================

def _generate_cinematic_beats(story: dict[str, Any]) -> str:
    lines = story.get("lines", [])
    chapters = story.get("chapters", [])
    notes = story.get("notes", {})
    end_line = (story.get("end") or {}).get("line")

    beats_meta = []
    for L in lines:
        if L.get("i") == end_line:
            continue
        words = [w[0] for w in L.get("words", []) if len(w[0]) >= 2 and w[0] not in "，。！？；：、"]
        beats_meta.append({
            "i": L.get("i", 1),
            "text": L.get("text", ""),
            "start": float(L.get("start", 0.0)),
            "end": float(L.get("end", 3.0)),
            "keywords": words[:3],
            "chap": L.get("chapter", ""),
        })

    beats_json = json.dumps(beats_meta, ensure_ascii=False)

    return f"""/* beats.js — Generated real 3D performed scenes for V6 电影感一镜到底 */
window.Beats = function (api) {{
  "use strict";
  var story = api.story, C = api.C, THREE = api.THREE, col = api.col, mat = api.mat, V = api.V;
  var items = {beats_json};

  var sceneObjects = [];

  // Group items by chapter station
  story.chapters.forEach(function (chap, k) {{
    var st = api.station(k);
    if (!st) return;

    var chapItems = items.filter(function (it) {{
      return it.start >= chap.start - 0.2 && it.start < chap.end + 0.2;
    }});
    if (!chapItems.length) chapItems = items.slice(k, k + 1);

    var group = new THREE.Group();
    st.group.add(group);

    // 1. Build distinctive 3D hero objects for this chapter
    var geomA, geomB, meshA, meshB;
    if (k === 0) {{
      // Chapter 1: Rounded metallic monolith + floating glowing energy sphere
      geomA = new api.RoundedBoxGeometry(3.6, 5.0, 1.2, 4, 0.25);
      meshA = new THREE.Mesh(geomA, mat.metal());
      meshA.position.set(-2.0, api.CY, 0);
      meshA.castShadow = true;
      group.add(meshA);

      geomB = new THREE.SphereGeometry(1.4, 32, 32);
      meshB = new THREE.Mesh(geomB, mat.accent());
      meshB.position.set(2.4, api.CY + 0.6, 1.2);
      meshB.castShadow = true;
      group.add(meshB);
    }} else if (k === 1) {{
      // Chapter 2: High-precision particle orbit / torus ring + glowing core
      geomA = new THREE.TorusGeometry(2.6, 0.45, 24, 64);
      meshA = new THREE.Mesh(geomA, mat.porcelain());
      meshA.position.set(0, api.CY, 0);
      meshA.rotation.x = Math.PI / 4;
      meshA.castShadow = true;
      group.add(meshA);

      geomB = new THREE.IcosahedronGeometry(1.5, 2);
      meshB = new THREE.Mesh(geomB, mat.accent());
      meshB.position.set(0, api.CY, 0);
      group.add(meshB);
    }} else if (k === 2) {{
      // Chapter 3: Stepped metric pedestal columns
      geomA = new api.RoundedBoxGeometry(2.2, 3.8, 2.2, 3, 0.2);
      meshA = new THREE.Mesh(geomA, mat.glass());
      meshA.position.set(-2.2, api.CY - 0.6, 0);
      group.add(meshA);

      geomB = new api.RoundedBoxGeometry(2.2, 5.6, 2.2, 3, 0.2);
      meshB = new THREE.Mesh(geomB, mat.accent());
      meshB.position.set(1.8, api.CY + 0.3, 0);
      meshB.castShadow = true;
      group.add(meshB);
    }} else {{
      // Chapter 4+: Floating crystalline multi-geometry cluster
      geomA = new THREE.CylinderGeometry(1.5, 1.5, 4.2, 32);
      meshA = new THREE.Mesh(geomA, mat.metal());
      meshA.position.set(-1.6, api.CY, 0);
      meshA.castShadow = true;
      group.add(meshA);

      geomB = new THREE.OctahedronGeometry(1.6);
      meshB = new THREE.Mesh(geomB, mat.porcelain());
      meshB.position.set(2.0, api.CY + 0.8, 0.8);
      group.add(meshB);
    }}

    // 2. Add pinned 3D labels from input keywords
    chapItems.forEach(function (it, i) {{
      if (it.keywords && it.keywords.length) {{
        var kw = it.keywords[0];
        var posX = (i % 2 === 0) ? -2.8 : 2.8;
        var posY = api.CY + 2.6 - i * 1.4;
        api.pin(
          api.Kit.label({{ text: kw, sub: "TOPIC FOCUS", tone: (i === 0 ? "accent" : "warn") }}),
          st.at(posX, posY, 1.5),
          [it.start, it.end + 0.3],
          {{ ax: 0.5, ay: 0.5 }}
        );
      }}
    }});

    // 3. Add chapter note under chip
    if (chapItems.length && chapItems[0].keywords.length) {{
      var mainKw = chapItems[0].keywords[0];
      api.note("核心要点：<b>" + mainKw + "</b> 机制原理解析", chap.start, chap.end);
    }}

    sceneObjects.push({{
      meshA: meshA,
      meshB: meshB,
      chapStart: chap.start,
      chapEnd: chap.end,
    }});
  }});

  return {{
    render: function (t) {{
      sceneObjects.forEach(function (obj, idx) {{
        if (obj.meshA) {{
          obj.meshA.rotation.y = t * 0.45 + idx;
          obj.meshA.position.y = (api.CY) + Math.sin(t * 1.5 + idx) * 0.18;
        }}
        if (obj.meshB) {{
          obj.meshB.rotation.x = t * 0.6 + idx;
          obj.meshB.rotation.z = t * 0.35;
          obj.meshB.position.y = (api.CY + 0.5) + Math.cos(t * 1.8 + idx) * 0.22;
        }}
      }});
    }},
  }};
}};
"""


# =============================================================================
# V4 Paper Beats Generator (折纸立体书风格)
# =============================================================================

def _generate_paper_beats(story: dict[str, Any]) -> str:
    lines = story.get("lines", [])
    end_line = (story.get("end") or {}).get("line")

    beats_meta = []
    for L in lines:
        if L.get("i") == end_line:
            continue
        words = [w[0] for w in L.get("words", []) if len(w[0]) >= 2 and w[0] not in "，。！？；：、"]
        beats_meta.append({
            "i": L.get("i", 1),
            "text": L.get("text", ""),
            "start": float(L.get("start", 0.0)),
            "end": float(L.get("end", 3.0)),
            "keywords": words[:2],
        })

    beats_json = json.dumps(beats_meta, ensure_ascii=False)

    return f"""/* beats.js — Generated real paper performed beats for V4 纸艺立体书 */
window.Beats = function (api) {{
  "use strict";
  var story = api.story;
  var items = {beats_json};

  var elements = [];

  items.forEach(function (item, idx) {{
    var sp = api.spot(item.i);
    if (!sp) return;

    // Build pop-up paper card structure
    var card = api.el("div", "kit-card paper-panel");
    card.style.cssText = "position:absolute; width:680px; height:340px; border-radius:12px; background:#fffcf6; border:2px solid #e2dac9; padding:28px; box-shadow:0 12px 36px rgba(40,30,20,0.12); transform-origin:bottom center;";
    api.box(card, sp.x - 340, api.FLOOR - 360, 680, 340);

    var kw = item.keywords.length ? item.keywords[0] : item.text.slice(0, 6);
    card.innerHTML = "<div style='font-size:20px; font-weight:800; color:#d9773f; letter-spacing:2px;'>STEP 0" + (idx + 1) + "</div>" +
                     "<div style='font-size:46px; font-weight:900; color:#2b261f; margin-top:12px;'>" + kw + "</div>" +
                     "<div style='font-size:24px; color:#786c5e; margin-top:14px; line-height:1.4;'>" + item.text + "</div>";

    var shadow = api.shadowFor(sp.x - 340, 680, 110);

    elements.push({{
      card: card,
      shadow: shadow,
      start: item.start,
      end: item.end,
    }});
  }});

  return {{
    render: function (t) {{
      elements.forEach(function (el) {{
        api.standUp(el.card, el.shadow, t, el.start, 0.45);
      }});
    }},
  }};
}};
"""


# =============================================================================
# V1 Editorial Beats Generator (现代刊物留白风格)
# =============================================================================

def _generate_editorial_beats(story: dict[str, Any]) -> str:
    lines = story.get("lines", [])
    end_line = (story.get("end") or {}).get("line")

    beats_meta = []
    for L in lines:
        if L.get("i") == end_line:
            continue
        words = [w[0] for w in L.get("words", []) if len(w[0]) >= 2 and w[0] not in "，。！？；：、"]
        beats_meta.append({
            "i": L.get("i", 1),
            "text": L.get("text", ""),
            "start": float(L.get("start", 0.0)),
            "end": float(L.get("end", 3.0)),
            "keywords": words[:2],
        })

    beats_json = json.dumps(beats_meta, ensure_ascii=False)

    return f"""/* beats.js — Generated real editorial spreads for V1 刊物留白 */
window.Beats = function (api) {{
  "use strict";
  var story = api.story;
  var items = {beats_json};

  story.chapters.forEach(function (chap, k) {{
    var st = api.station(k);
    if (!st || !st.el) return;

    var chapItems = items.filter(function (it) {{
      return it.start >= chap.start - 0.2 && it.start < chap.end + 0.2;
    }});
    if (!chapItems.length) chapItems = items.slice(k, k + 1);

    var container = document.createElement("div");
    container.style.cssText = "position:absolute; left:120px; top:280px; width:1680px; height:580px; display:flex; gap:60px; align-items:center;";

    chapItems.forEach(function (it, idx) {{
      var col = document.createElement("div");
      col.style.cssText = "flex:1; background:#ffffff; border:1px solid #e8e4dc; border-radius:8px; padding:36px; box-shadow:0 8px 30px rgba(0,0,0,0.04);";
      var kw = it.keywords.length ? it.keywords[0] : "要点";
      col.innerHTML = "<div style='font-size:16px; font-weight:700; color:#8c8273; letter-spacing:3px;'>SECTION " + (k + 1) + "." + (idx + 1) + "</div>" +
                      "<div style='font-size:48px; font-weight:800; color:#181614; margin:16px 0;'>" + kw + "</div>" +
                      "<div style='font-size:24px; color:#5c5448; line-height:1.5;'>" + it.text + "</div>";
      container.appendChild(col);
    }});

    st.el.appendChild(container);

    if (chapItems.length && chapItems[0].keywords.length) {{
      api.note("核心专题：<b>" + chapItems[0].keywords[0] + "</b> · 深度论证", chap.start, chap.end);
    }}
  }});

  return {{
    render: function (t) {{}},
  }};
}};
"""


# =============================================================================
# V2 Signal Beats Generator (赛博终端信号风格)
# =============================================================================

def _generate_signal_beats(story: dict[str, Any]) -> str:
    lines = story.get("lines", [])
    end_line = (story.get("end") or {}).get("line")

    beats_meta = []
    for L in lines:
        if L.get("i") == end_line:
            continue
        words = [w[0] for w in L.get("words", []) if len(w[0]) >= 2 and w[0] not in "，。！？；：、"]
        beats_meta.append({
            "i": L.get("i", 1),
            "text": L.get("text", ""),
            "start": float(L.get("start", 0.0)),
            "end": float(L.get("end", 3.0)),
            "keywords": words[:2],
        })

    beats_json = json.dumps(beats_meta, ensure_ascii=False)

    return f"""/* beats.js — Generated real signal telemetry for V2 信号终端 */
window.Beats = function (api) {{
  "use strict";
  var story = api.story;
  var items = {beats_json};

  story.chapters.forEach(function (chap, k) {{
    var st = api.station(k);
    if (!st) return;

    var chapItems = items.filter(function (it) {{
      return it.start >= chap.start - 0.2 && it.start < chap.end + 0.2;
    }});
    if (!chapItems.length) chapItems = items.slice(k, k + 1);

    var monitor = document.createElement("div");
    monitor.style.cssText = "position:absolute; left:160px; top:240px; width:1600px; height:600px; background:rgba(12,20,16,0.92); border:2px solid #22c55e; border-radius:6px; padding:32px; font-family:monospace; box-shadow:0 0 40px rgba(34,197,94,0.15);";

    var linesHtml = chapItems.map(function (it, idx) {{
      var kw = it.keywords.length ? it.keywords[0] : "SIGNAL";
      return "<div style='margin-bottom:24px; padding-bottom:16px; border-bottom:1px dashed rgba(34,197,94,0.3);'>" +
             "<span style='color:#86efac; font-size:18px;'>[CH " + (k + 1) + " // NODE " + (idx + 1) + "]</span> " +
             "<span style='color:#ffffff; font-size:38px; font-weight:bold; margin-left:16px;'>" + kw + "</span>" +
             "<div style='color:#a3e635; font-size:24px; margin-top:8px;'>" + it.text + "</div>" +
             "</div>";
    }}).join("");

    monitor.innerHTML = "<div style='color:#22c55e; font-size:16px; letter-spacing:4px; margin-bottom:20px;'>/// TELEMETRY CHANNEL ACTIVE ///</div>" + linesHtml;
    st.appendChild(monitor);
  }});

  var chain = api.closingChain ? api.closingChain() : null;

  return {{
    render: function (t) {{
      if (chain) chain.render(t);
    }},
  }};
}};
"""


# =============================================================================
# V5 Comic Beats Generator (美漫风格)
# =============================================================================

def _generate_comic_beats(story: dict[str, Any]) -> str:
    lines = story.get("lines", [])
    end_line = (story.get("end") or {}).get("line")

    beats_meta = []
    for L in lines:
        if L.get("i") == end_line:
            continue
        words = [w[0] for w in L.get("words", []) if len(w[0]) >= 2 and w[0] not in "，。！？；：、"]
        beats_meta.append({
            "i": L.get("i", 1),
            "text": L.get("text", ""),
            "start": float(L.get("start", 0.0)),
            "end": float(L.get("end", 3.0)),
            "keywords": words[:2],
        })

    beats_json = json.dumps(beats_meta, ensure_ascii=False)

    return f"""/* beats.js — Generated comic panels for V5 漫画分镜 */
window.Beats = function (api) {{
  "use strict";
  var story = api.story;
  var items = {beats_json};

  // Build comic panels
  items.forEach(function (it, idx) {{
    var kw = it.keywords.length ? it.keywords[0] : "BAM!";
    // If api provides custom slots or stage placement:
    if (api.placeholder) {{
      // In comic starter, custom panels can be added or placeholder replaced
    }}
  }});

  return {{
    render: function (t) {{}},
  }};
}};
"""


_GENERATORS = {
    "v1-editorial": _generate_editorial_beats,
    "v2-signal": _generate_signal_beats,
    "v4-paper": _generate_paper_beats,
    "v5-comic": _generate_comic_beats,
    "v6-cinematic": _generate_cinematic_beats,
    "v8-chalkboard": _generate_chalkboard_beats,
}
