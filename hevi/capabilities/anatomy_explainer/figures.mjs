import * as k from "../../../third_party/anatomy/kit/iso-kit.mjs";
import { writeFileSync, mkdirSync } from "node:fs";

export function generateFigureHtml(objectName, aspect, seed, outPath) {
  const isPortrait = aspect === "9:16";
  const width = isPortrait ? 1080 : 1920;
  const height = isPortrait ? 1920 : 1080;

  const P = k.fitProjection([[-100, -100, 0], [100, 100, 100]], width, height, { pad: 100, azimuth: 45, elevation: 30 });

  const titleText = {
    windmill: "小风车转转转",
    waterwheel: "快乐转水车",
    soap_pump: "按压洗手液",
    clock_gear: "滴答小闹钟"
  }[objectName] || "科普小机器";

  let svgBody = "";
  if (objectName === "windmill") {
    const basePlate = { x: -60, y: -60, w: 120, d: 120, r: 12 };
    svgBody += `<g class="color-yellow">` + k.solidSvg(k.slabOf(basePlate, 0, 15, P, 8, 2), { tone: "hi" }) + `</g>`;
    svgBody += `<g class="color-green">` + k.solidSvg(k.cylinder(0, 0, 25, 15, 80, P, 32, 2), { tone: "mid" }) + `</g>`;
    svgBody += `<g class="color-red">` + k.solidSvg(k.cylinder(0, 0, 30, 95, 25, P, 32, 2), { tone: "hi" }) + `</g>`;
    svgBody += `<g data-part="blades" transform="translate(0, 0)">`;
    for (let i = 0; i < 4; i++) {
      svgBody += `<g class="color-blue">` + k.solidSvg(k.slabOf({ x: -8, y: -35, w: 16, d: 35, r: 4 }, 120, 8, P, 4), { tone: "hi" }) + `</g>`;
    }
    svgBody += `</g>`;
  } else if (objectName === "waterwheel") {
    const basePlate = { x: -80, y: -50, w: 160, d: 100, r: 10 };
    svgBody += `<g class="color-yellow">` + k.solidSvg(k.slabOf(basePlate, 0, 12, P, 8, 2), { tone: "hi" }) + `</g>`;
    svgBody += `<g class="color-blue">` + k.solidSvg(k.slabOf({ x: -50, y: -30, w: 100, d: 60, r: 8 }, 12, 40, P, 6, 2), { tone: "mid" }) + `</g>`;
    svgBody += `<g data-part="wheel" class="color-red">`;
    svgBody += k.solidSvg(k.cylinder(0, 10, 45, 30, 15, P, 36, 2), { tone: "hi" });
    svgBody += `</g>`;
  } else if (objectName === "soap_pump") {
    const bottle = { x: -40, y: -40, w: 80, d: 80, r: 16 };
    svgBody += `<g class="color-green">` + k.solidSvg(k.slabOf(bottle, 0, 90, P, 12, 4), { tone: "hi" }) + `</g>`;
    svgBody += `<g data-part="pumpHead" transform="translate(0, 0)">`;
    svgBody += `<g class="color-red">` + k.solidSvg(k.cylinder(0, 0, 18, 90, 25, P, 24, 2), { tone: "mid" }) + `</g>`;
    svgBody += `<g class="color-yellow">` + k.solidSvg(k.slabOf({ x: -25, y: -8, w: 35, d: 16, r: 6 }, 110, 12, P, 4), { tone: "hi" }) + `</g>`;
    svgBody += `</g>`;
  } else {
    const bodyBox = { x: -60, y: -60, w: 120, d: 120, r: 14 };
    svgBody += `<g class="color-blue">` + k.solidSvg(k.slabOf(bodyBox, 0, 50, P, 8, 3), { tone: "hi" }) + `</g>`;
    svgBody += `<g data-part="gearMain" class="color-red">`;
    svgBody += k.solidSvg(k.cylinder(-25, 0, 30, 50, 10, P, 32, 2), { tone: "mid" });
    svgBody += `</g>`;
    svgBody += `<g data-part="gearSub" class="color-yellow">`;
    svgBody += k.solidSvg(k.cylinder(30, 20, 20, 50, 10, P, 24, 2), { tone: "hi" });
    svgBody += `</g>`;
  }

  const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>${titleText}</title>
<style>
  html, body {
    margin: 0;
    padding: 0;
    width: ${width}px;
    height: ${height}px;
    background-color: #2563eb !important;
    background: #2563eb !important;
    font-family: system-ui, -apple-system, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }
  .title-label {
    position: absolute;
    top: ${isPortrait ? '120px' : '60px'};
    font-size: ${isPortrait ? '72px' : '64px'};
    font-weight: bold;
    color: #ffffff;
    background: #dc2626;
    padding: 16px 40px;
    border-radius: 36px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.3);
    letter-spacing: 2px;
    z-index: 10;
  }
  svg {
    width: ${width}px;
    height: ${height}px;
    position: absolute;
    top: 0;
    left: 0;
    z-index: 1;
  }
  .color-red {
    --anatomy-paper: #ef4444; --anatomy-top: #f87171;
    --anatomy-shade-0: #b91c1c; --anatomy-shade-1: #dc2626; --anatomy-shade-2: #ef4444; --anatomy-shade-3: #f87171;
    --anatomy-hi: #991b1b; --anatomy-lo: #7f1d1d; --anatomy-face: #ef4444; --anatomy-lit-top: #f87171; --anatomy-lit-shade: #dc2626;
  }
  .color-green {
    --anatomy-paper: #22c55e; --anatomy-top: #4ade80;
    --anatomy-shade-0: #15803d; --anatomy-shade-1: #16a34a; --anatomy-shade-2: #22c55e; --anatomy-shade-3: #4ade80;
    --anatomy-hi: #166534; --anatomy-lo: #14532d; --anatomy-face: #22c55e; --anatomy-lit-top: #4ade80; --anatomy-lit-shade: #16a34a;
  }
  .color-yellow {
    --anatomy-paper: #eab308; --anatomy-top: #facc15;
    --anatomy-shade-0: #a16207; --anatomy-shade-1: #ca8a04; --anatomy-shade-2: #eab308; --anatomy-shade-3: #facc15;
    --anatomy-hi: #854d0e; --anatomy-lo: #713f12; --anatomy-face: #eab308; --anatomy-lit-top: #facc15; --anatomy-lit-shade: #ca8a04;
  }
  .color-blue {
    --anatomy-paper: #3b82f6; --anatomy-top: #60a5fa;
    --anatomy-shade-0: #1d4ed8; --anatomy-shade-1: #2563eb; --anatomy-shade-2: #3b82f6; --anatomy-shade-3: #60a5fa;
    --anatomy-hi: #1e40af; --anatomy-lo: #1e3a8a; --anatomy-face: #3b82f6; --anatomy-lit-top: #60a5fa; --anatomy-lit-shade: #2563eb;
  }
  ${k.ISO_CSS}
</style>
</head>
<body>
  <div class="title-label" data-readout>${titleText}</div>
  <svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">
    <rect width="${width}" height="${height}" fill="#2563eb"/>
    <g transform="translate(${width/2}, ${height/2 + 50})">
      ${svgBody}
    </g>
  </svg>
<script>
  window.__heviSeek = function(t) {
    const obj = "${objectName}";
    if (obj === "windmill") {
      const blades = document.querySelector('[data-part="blades"]');
      if (blades) {
        const deg = t * 360 * 3;
        blades.setAttribute("transform", "translate(0, 20) rotate(" + deg + ")");
      }
    } else if (obj === "waterwheel") {
      const wheel = document.querySelector('[data-part="wheel"]');
      if (wheel) {
        const deg = t * 360 * 2;
        wheel.setAttribute("transform", "rotate(" + deg + ")");
      }
    } else if (obj === "soap_pump") {
      const head = document.querySelector('[data-part="pumpHead"]');
      if (head) {
        const dy = Math.sin(t * Math.PI * 4) * 15;
        head.setAttribute("transform", "translate(0, " + dy + ")");
      }
    } else if (obj === "clock_gear") {
      const gMain = document.querySelector('[data-part="gearMain"]');
      const gSub = document.querySelector('[data-part="gearSub"]');
      if (gMain && gSub) {
        const deg1 = t * 360 * 2;
        const deg2 = -t * 360 * 4;
        gMain.setAttribute("transform", "rotate(" + deg1 + ")");
        gSub.setAttribute("transform", "rotate(" + deg2 + ")");
      }
    }
  };
  window.__heviSeek(0);
</script>
</body>
</html>`;

  mkdirSync(outPath.split("/").slice(0, -1).join("/"), { recursive: true });
  writeFileSync(outPath, html, "utf-8");
  return outPath;
}
