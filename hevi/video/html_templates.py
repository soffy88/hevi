"""HTML 视频模板库 — 21 个内置模板 (5 类)。

对标 nexu-io/html-video 的模板系统。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["HtmlVideoTemplate", "list_html_templates", "get_html_template"]


class HtmlVideoTemplate(BaseModel):
    """HTML 视频模板。"""
    id: str
    name: str
    category: str
    description: str
    html_source: str
    css: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)

_REGISTRY: dict[str, dict[str, Any]] = {}
# Variable type aliases for compact definitions
_S, _N, _B = "string", "number", "boolean"


def _V(specs: list[tuple]) -> list[dict[str, Any]]:
    return [{"name": s[0], "type": s[1], "default": s[2]} for s in specs]


def _t(tid, name, desc, cat, html, css, variables):
    _REGISTRY[tid] = dict(
        id=tid, name=name, description=desc, category=cat,
        html_source=html, css=css, variables=variables,
        preview_thumbnail=f"/templates/{tid}.png",
    )


BASE_CSS = (
    "*{margin:0;padding:0;box-sizing:border-box}"
    "body{width:100%;height:100%;overflow:hidden;font-family:'Inter',system-ui,sans-serif}"
    ".frame{width:100%;height:100%;display:flex;flex-direction:column;"
    "align-items:center;justify-content:center;position:relative;"
    "animation:fadeIn .4s ease-out}"
    "@keyframes fadeIn{from{opacity:0}to{opacity:1}}"
)

# ── Social Media (5) ────────────────────────────────────────────────────

_t("vertical-story", "竖版故事", "9:16 竖版全屏故事", "social",
   '<div class="frame" style="background:{{bg_color}}">'
   '<h1 style="color:{{title_color}}">{{title}}</h1>'
   '<p style="color:{{text_color}}">{{text}}</p></div>',
   ".frame{background:linear-gradient(135deg,#667eea,#764ba2)}"
   "h1{font-size:3em;font-weight:800;text-align:center;padding:0 20px}"
   "p{font-size:1.5em;margin-top:20px;text-align:center;padding:0 20px}",
   _V([("title", _S, "Story Title"), ("text", _S, "Your story here"),
       ("bg_color", _S, "#1a1a2e"), ("title_color", _S, "#fff"),
       ("text_color", _S, "#ccc")]))

_t("square-post", "方帖", "1:1 方形社交帖子", "social",
   '<div class="frame" style="background:{{bg_color}}">'
   '<h1>{{title}}</h1><div class="grid">{{images}}</div><p>{{caption}}</p></div>',
   ".frame{padding:40px}h1{font-size:2.5em;font-weight:700;margin-bottom:20px}"
   ".grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px}"
   "p{font-size:1.2em;opacity:.8}",
   _V([("title", _S, "Post Title"), ("images", _S, ""),
       ("caption", _S, "Post caption"), ("bg_color", _S, "#fff")]))

_t("carousel-slide", "轮播帧", "轮播单帧:标题+正文+CTA", "social",
   '<div class="frame" style="background:{{bg_color}}">'
   '<h1>{{title}}</h1><p>{{body}}</p><div class="cta">{{cta_text}}</div></div>',
   ".frame{padding:60px;text-align:center}"
   "h1{font-size:3em;font-weight:800;margin-bottom:24px}"
   "p{font-size:1.4em;line-height:1.6;margin-bottom:40px;max-width:600px}"
   ".cta{background:{{accent}};color:#fff;padding:16px 48px;border-radius:30px;"
   "font-size:1.2em;font-weight:600;display:inline-block}",
   _V([("title", _S, "Slide Title"), ("body", _S, "Slide content"),
       ("cta_text", _S, "Learn More"), ("bg_color", _S, "#0f0f23"),
       ("accent", _S, "#6366f1")]))

_t("reel-intro", "Reels 开场", "Reels/Shorts 开场动画", "social",
   '<div class="frame" style="background:{{bg_color}}">'
   '<div class="logo">{{logo_text}}</div><h1>{{title}}</h1></div>',
   ".frame{background:#000}.logo{font-size:4em;font-weight:900;"
   "animation:zoomIn .8s ease-out;margin-bottom:30px}"
   "h1{font-size:2em;font-weight:300;letter-spacing:.3em;text-transform:uppercase;"
   "opacity:0;animation:fadeUp .6s .4s ease-out forwards}"
   "@keyframes zoomIn{from{transform:scale(0);opacity:0}to{transform:scale(1);opacity:1}}"
   "@keyframes fadeUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:none}}",
   _V([("title", _S, "REEL TITLE"), ("logo_text", _S, "LOGO"),
       ("bg_color", _S, "#000")]))

_t("tweet-card", "推文卡片", "推文风格卡片", "social",
   '<div class="frame"><div class="card">'
   '<div class="header"><div class="avatar">{{avatar_initials}}</div>'
   '<div class="info"><strong>{{display_name}}</strong>'
   '<span>@{{handle}}</span></div></div>'
   '<p class="tweet-text">{{tweet_text}}</p>'
   '<div class="metrics">'
   '<span>♡ {{likes}}</span><span>↻ {{retweets}}</span>'
   '<span>💬 {{replies}}</span></div></div></div>',
   ".frame{background:#15202b}.card{background:#192734;border-radius:16px;"
   "padding:24px;max-width:600px;width:90%}"
   ".header{display:flex;align-items:center;gap:12px;margin-bottom:16px}"
   ".avatar{width:48px;height:48px;border-radius:50%;background:#1da1f2;"
   "display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff}"
   ".info strong{color:#fff;display:block}.info span{color:#8899a6;font-size:.9em}"
   ".tweet-text{color:#fff;font-size:1.3em;line-height:1.5;margin-bottom:16px}"
   ".metrics{color:#8899a6;display:flex;gap:24px;font-size:.95em}",
   _V([("avatar_initials", _S, "JD"), ("display_name", _S, "John Doe"),
       ("handle", _S, "johndoe"), ("tweet_text", _S, "Hello world!"),
       ("likes", _S, "1.2K"), ("retweets", _S, "342"), ("replies", _S, "56")]))

# ── Explainer (5) ────────────────────────────────────────────────────────

_t("explainer-intro", "解说开场", "解说视频开场", "explainer",
   '<div class="frame" style="background:{{bg_color}}">'
   '<div class="logo">{{logo_text}}</div>'
   '<h1>{{title}}</h1><p>{{subtitle}}</p></div>',
   ".frame{background:linear-gradient(180deg,#0f0c29,#302b63,#24243e)}"
   ".logo{font-size:1.2em;letter-spacing:.5em;text-transform:uppercase;color:{{accent}};margin-bottom:40px}"
   "h1{font-size:4em;font-weight:900;text-align:center}"
   "p{font-size:1.5em;color:#8892b0;margin-top:20px}",
   _V([("title", _S, "Video Title"), ("subtitle", _S, "A brief subtitle"),
       ("logo_text", _S, "BRAND"), ("bg_color", _S, "#0f0c29"),
       ("accent", _S, "#64ffda")]))

_t("bullet-points", "要点列表", "动画要点列表", "explainer",
   '<div class="frame" style="background:{{bg_color}}">'
   '<h2>{{heading}}</h2><ul>{{bullets}}</ul></div>',
   ".frame{padding:80px;align-items:flex-start;justify-content:center}"
   "h2{font-size:2.5em;font-weight:700;color:{{accent}};margin-bottom:40px}"
   "ul{list-style:none}li{font-size:1.5em;color:#e0e0e0;padding:12px 0;"
   "border-bottom:1px solid rgba(255,255,255,.1)}"
   "li::before{content:'→';color:{{accent}};margin-right:16px;font-weight:700}",
   _V([("heading", _S, "Key Points"),
       ("bullets", _S, "<li>Point 1</li><li>Point 2</li>"),
       ("bg_color", _S, "#1a1a2e"), ("accent", _S, "#e94560")]))

_t("stat-highlight", "数据高亮", "大数字+标签+上下文", "explainer",
   '<div class="frame" style="background:{{bg_color}}">'
   '<div class="number">{{number}}</div>'
   '<div class="label">{{label}}</div>'
   '<div class="context">{{context}}</div></div>',
   ".frame{text-align:center}.number{font-size:8em;font-weight:900;color:{{accent}};line-height:1}"
   ".label{font-size:2em;font-weight:600;margin-top:20px}"
   ".context{font-size:1.2em;color:#888;margin-top:16px;max-width:500px}",
   _V([("number", _S, "42%"), ("label", _S, "Growth Rate"),
       ("context", _S, "Year over year increase"), ("bg_color", _S, "#0a0a0a"),
       ("accent", _S, "#00d4ff")]))

_t("quote-overlay", "引用覆盖", "引用文本+署名", "explainer",
   '<div class="frame" style="background:{{bg_color}}">'
   '<div class="qm">"</div><blockquote>{{quote_text}}</blockquote>'
   '<cite>— {{attribution}}</cite></div>',
   ".frame{text-align:center;padding:80px}"
   ".qm{font-size:6em;color:{{accent}};line-height:.5;font-family:Georgia}"
   "blockquote{font-size:2.2em;font-style:italic;font-family:Georgia;"
   "line-height:1.4;max-width:700px;margin:20px auto}"
   "cite{font-size:1.3em;color:#999;font-style:normal;display:block;margin-top:30px}",
   _V([("quote_text", _S, "An inspiring quote goes here"),
       ("attribution", _S, "Author Name"), ("bg_color", _S, "#1a1a2e"),
       ("accent", _S, "#ffd700")]))

_t("chapter-divider", "章节分隔", "章节号+标题+色块", "explainer",
   '<div class="frame" style="background:{{bg_color}}">'
   '<div class="cn" style="color:{{accent}}">{{chapter_number}}</div>'
   '<div class="dv" style="background:{{accent}}"></div>'
   '<h2>{{chapter_title}}</h2></div>',
   ".frame{text-align:center}"
   ".cn{font-size:6em;font-weight:900;opacity:.3;font-family:Georgia}"
   ".dv{width:80px;height:4px;margin:20px auto;border-radius:2px}"
   "h2{font-size:3em;font-weight:700;letter-spacing:.1em}",
   _V([("chapter_number", _S, "01"), ("chapter_title", _S, "Chapter Title"),
       ("bg_color", _S, "#0d1117"), ("accent", _S, "#58a6ff")]))

# ── Marketing (4) ────────────────────────────────────────────────────────

_t("product-showcase", "产品展示", "产品图+标题+价格+CTA", "marketing",
   '<div class="frame" style="background:{{bg_color}}">'
   '<div class="pi">{{product_image}}</div><h2>{{product_name}}</h2>'
   '<div class="price">{{price}}</div><div class="cta">{{cta_text}}</div></div>',
   ".frame{padding:60px}.pi{width:300px;height:300px;border-radius:16px;"
   "background:#333;margin-bottom:30px;display:flex;align-items:center;justify-content:center;overflow:hidden}"
   "h2{font-size:2.5em;font-weight:700;margin-bottom:12px}"
   ".price{font-size:2em;color:{{accent}};font-weight:700;margin-bottom:30px}"
   ".cta{background:{{accent}};color:#fff;padding:16px 48px;border-radius:30px;font-size:1.2em;font-weight:600}",
   _V([("product_name", _S, "Product Name"), ("product_image", _S, ""),
       ("price", _S, "$99.99"), ("cta_text", _S, "Buy Now"),
       ("bg_color", _S, "#fff"), ("accent", _S, "#ff6b35")]))

_t("testimonial", "用户评价", "头像+姓名+引用+评分", "marketing",
   '<div class="frame" style="background:{{bg_color}}"><div class="card">'
   '<div class="avatar">{{avatar}}</div><div class="stars">{{rating}}</div>'
   '<blockquote>"{{quote}}"</blockquote><div class="name">{{name}}</div>'
   '<div class="role">{{role}}</div></div></div>',
   ".frame{background:#f8f9fa}.card{background:#fff;border-radius:20px;padding:40px;"
   "max-width:600px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.1)}"
   ".avatar{width:80px;height:80px;border-radius:50%;background:#ddd;margin:0 auto 20px}"
   ".stars{color:#f59e0b;font-size:1.5em;margin-bottom:20px}"
   "blockquote{font-size:1.3em;font-style:italic;line-height:1.6;color:#333;margin-bottom:20px}"
   ".name{font-weight:700;font-size:1.1em}.role{color:#666;font-size:.95em}",
   _V([("avatar", _S, ""), ("name", _S, "Jane Smith"),
       ("quote", _S, "Amazing product!"), ("rating", _S, "★★★★★"),
       ("role", _S, "CEO, Company"), ("bg_color", _S, "#f0f0f0")]))

_t("price-comparison", "价格对比", "多方案对比表", "marketing",
   '<div class="frame" style="background:{{bg_color}}">'
   '<h2>{{heading}}</h2><div class="plans">{{plans}}</div></div>',
   ".frame{padding:60px}h2{font-size:2.5em;font-weight:700;margin-bottom:40px}"
   ".plans{display:flex;gap:24px;justify-content:center}"
   ".plan{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);"
   "border-radius:16px;padding:32px;min-width:220px;text-align:center}"
   ".plan.hl{border-color:{{accent}};transform:scale(1.05)}"
   ".pn{font-size:1.3em;font-weight:600;margin-bottom:12px}"
   ".pp{font-size:2.5em;font-weight:900;color:{{accent}};margin-bottom:20px}",
   _V([("heading", _S, "Choose Your Plan"), ("plans", _S, ""),
       ("bg_color", _S, "#0f0f23"), ("accent", _S, "#6366f1")]))

_t("countdown-timer", "倒计时", "倒计时器", "marketing",
   '<div class="frame" style="background:{{bg_color}}">'
   '<h2>{{event_name}}</h2><div class="timer">'
   '<div class="u"><span class="n">{{days}}</span><span class="l">DAYS</span></div>'
   '<div class="u"><span class="n">{{hours}}</span><span class="l">HRS</span></div>'
   '<div class="u"><span class="n">{{minutes}}</span><span class="l">MIN</span></div>'
   '<div class="u"><span class="n">{{seconds}}</span><span class="l">SEC</span></div>'
   '</div></div>',
   ".frame{text-align:center}h2{font-size:2.5em;font-weight:700;margin-bottom:40px}"
   ".timer{display:flex;gap:24px;justify-content:center}"
   ".u{background:rgba(255,255,255,.05);border-radius:12px;padding:24px 32px}"
   ".n{font-size:4em;font-weight:900;color:{{accent}};display:block}"
   ".l{font-size:.9em;color:#888;letter-spacing:.2em}",
   _V([("event_name", _S, "LAUNCH IN"), ("days", _S, "07"),
       ("hours", _S, "12"), ("minutes", _S, "34"), ("seconds", _S, "56"),
       ("bg_color", _S, "#0a0a0a"), ("accent", _S, "#ff4757")]))

# ── Data (4) ─────────────────────────────────────────────────────────────

_t("animated-chart", "动画图表", "CSS 动画图表", "data",
   '<div class="frame" style="background:{{bg_color}}">'
   '<h2>{{title}}</h2><div class="chart {{chart_type}}">{{chart_data}}</div></div>',
   ".frame{padding:60px}h2{font-size:2em;font-weight:700;margin-bottom:40px}"
   ".chart{display:flex;align-items:flex-end;gap:16px;height:300px;padding:20px}"
   ".bar{background:{{bar_color}};border-radius:8px 8px 0 0;flex:1;"
   "animation:growUp .8s ease-out;transform-origin:bottom}"
   "@keyframes growUp{from{transform:scaleY(0)}to{transform:scaleY(1)}}",
   _V([("title", _S, "Chart Title"), ("chart_type", _S, "bar"),
       ("chart_data", _S, ""), ("bg_color", _S, "#1a1a2e"),
       ("bar_color", _S, "#6366f1")]))

_t("number-counter", "数字计数器", "动态数字计数器", "data",
   '<div class="frame" style="background:{{bg_color}}">'
   '<div class="c"><span class="p">{{prefix}}</span>'
   '<span class="v">{{end_value}}</span>'
   '<span class="s">{{suffix}}</span></div>'
   '<div class="label">{{label}}</div></div>',
   ".frame{text-align:center}"
   ".c{display:flex;align-items:baseline;justify-content:center}"
   ".p,.s{font-size:3em;font-weight:700;color:{{accent}}}"
   ".v{font-size:{{font_size}};font-weight:900;color:{{accent}};animation:pulse .6s ease-out}"
   ".label{font-size:1.5em;color:#999;margin-top:20px}"
   "@keyframes pulse{from{transform:scale(.5);opacity:0}to{transform:scale(1);opacity:1}}",
   _V([("start_value", _N, 0), ("end_value", _S, "10000"),
       ("prefix", _S, "$"), ("suffix", _S, "+"),
       ("label", _S, "Revenue Generated"), ("bg_color", _S, "#0a0a0a"),
       ("accent", _S, "#00ff88"), ("font_size", _S, "6em")]))

_t("progress-tracker", "进度追踪", "步骤进度指示器", "data",
   '<div class="frame" style="background:{{bg_color}}">'
   '<h2>{{heading}}</h2><div class="tr">{{steps}}</div>'
   '<div class="cl">{{current_label}}</div></div>',
   ".frame{padding:60px}h2{font-size:2em;font-weight:700;margin-bottom:40px}"
   ".tr{display:flex;align-items:center;gap:8px;margin-bottom:30px}"
   ".step{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;"
   "justify-content:center;font-weight:700;font-size:1.1em}"
   ".step.done{background:{{accent}};color:#fff}"
   ".step.cur{border:3px solid {{accent}};color:{{accent}}}"
   ".step.pend{background:rgba(255,255,255,.1);color:#666}"
   ".conn{flex:1;height:3px;background:rgba(255,255,255,.1)}"
   ".conn.done{background:{{accent}}}.cl{font-size:1.3em;color:#ccc}",
   _V([("heading", _S, "Progress"), ("steps", _S, ""),
       ("current", _N, 2), ("current_label", _S, "Current Step"),
       ("bg_color", _S, "#1a1a2e"), ("accent", _S, "#22c55e")]))

_t("heatmap-grid", "热力图", "数据热力图网格", "data",
   '<div class="frame" style="background:{{bg_color}}">'
   '<h2>{{title}}</h2><div class="hm">{{cells}}</div></div>',
   ".frame{padding:60px}h2{font-size:2em;font-weight:700;margin-bottom:30px}"
   ".hm{display:grid;grid-template-columns:repeat(7,{{cell_size}});gap:4px;justify-content:center}"
   ".cell{width:{{cell_size}};height:{{cell_size}};border-radius:{{cell_radius}}}",
   _V([("title", _S, "Activity Heatmap"), ("cells", _S, ""),
       ("color_scale", _S, "#161b22,#0e4429,#006d32,#26a641,#39d353"),
       ("bg_color", _S, "#0d1117"), ("cell_size", _S, "40px"),
       ("cell_radius", _S, "4px")]))

# ── Creative (3) ─────────────────────────────────────────────────────────

_t("kinetic-typography", "动态排版", "CSS 动画文字", "creative",
   '<div class="frame" style="background:{{bg_color}}">'
   '<div class="k {{animation_style}}">{{text}}</div></div>',
   ".frame{text-align:center;padding:40px}"
   ".k{font-size:{{font_size}};font-weight:900;line-height:1.2;font-family:{{font_family}}}"
   ".wave span{display:inline-block;animation:wave 1.5s ease-in-out infinite}"
   "@keyframes wave{0%,100%{transform:translateY(0)}50%{transform:translateY(-20px)}}",
   _V([("text", _S, "KINETIC TEXT"), ("animation_style", _S, "wave"),
       ("font_size", _S, "4em"), ("font_family", _S, "system-ui"),
       ("bg_color", _S, "#0a0a0a"), ("text_color", _S, "#fff")]))

_t("split-screen", "分屏对比", "左右分屏", "creative",
   '<div class="frame"><div class="sp">'
   '<div class="sd l" style="background:{{left_bg}}"><div class="ct">{{left_content}}</div></div>'
   '<div class="sd r" style="background:{{right_bg}}"><div class="ct">{{right_content}}</div></div>'
   '</div></div>',
   ".frame{padding:0}.sp{display:flex;width:100%;height:100%}"
   ".sd{flex:1;display:flex;align-items:center;justify-content:center;padding:40px}"
   ".ct{max-width:400px;text-align:center}"
   ".l .ct{animation:sR .6s ease-out}.r .ct{animation:sL .6s ease-out}"
   "@keyframes sR{from{transform:translateX(-40px);opacity:0}to{transform:none;opacity:1}}"
   "@keyframes sL{from{transform:translateX(40px);opacity:0}to{transform:none;opacity:1}}",
   _V([("left_content", _S, "Left Side"), ("right_content", _S, "Right Side"),
       ("left_bg", _S, "#1a1a2e"), ("right_bg", _S, "#e94560")]))

_t("photo-collage", "照片拼贴", "多照片拼贴布局", "creative",
   '<div class="frame" style="background:{{bg_color}}">'
   '<div class="col">{{images}}</div></div>',
   ".frame{padding:40px}.col{display:grid;"
   "grid-template-columns:repeat(auto-fill,minmax({{cell_size}},1fr));"
   "gap:{{gap}};width:100%;height:80%}"
   ".col img{width:100%;height:100%;object-fit:cover;border-radius:{{border_radius}}}",
   _V([("images", _S, ""), ("layout", _S, "grid"),
       ("border_radius", _S, "12px"), ("gap", _S, "12px"),
       ("bg_color", _S, "#1a1a2e"), ("cell_size", _S, "200px")]))


def list_html_templates() -> list[HtmlVideoTemplate]:
    """返回所有已注册模板。"""
    results: list[HtmlVideoTemplate] = []
    for entry in _REGISTRY.values():
        # Convert variable list → dict for Pydantic model
        var_dict = {}
        defaults_dict = {}
        for v in entry.get("variables", []):
            if isinstance(v, dict):
                var_dict[v["name"]] = v.get("type", "string")
                if "default" in v:
                    defaults_dict[v["name"]] = v["default"]
        results.append(HtmlVideoTemplate(
            id=entry["id"],
            name=entry["name"],
            category=entry.get("category", ""),
            description=entry.get("description", ""),
            html_source=entry.get("html_source", ""),
            css=entry.get("css", ""),
            variables=var_dict,
            defaults=defaults_dict,
        ))
    return results


def get_html_template(template_id: str) -> HtmlVideoTemplate:
    """按 ID 获取模板。"""
    tpl = _REGISTRY.get(template_id)
    if tpl is None:
        raise ValueError(
            f"HTML template not found: {template_id!r}. "
            f"Available: {', '.join(sorted(_REGISTRY))}"
        )
    var_dict = {}
    defaults_dict = {}
    for v in tpl.get("variables", []):
        if isinstance(v, dict):
            var_dict[v["name"]] = v.get("type", "string")
            if "default" in v:
                defaults_dict[v["name"]] = v["default"]
    return HtmlVideoTemplate(
        id=tpl["id"],
        name=tpl["name"],
        category=tpl.get("category", ""),
        description=tpl.get("description", ""),
        html_source=tpl.get("html_source", ""),
        css=tpl.get("css", ""),
        variables=var_dict,
        defaults=defaults_dict,
    )
