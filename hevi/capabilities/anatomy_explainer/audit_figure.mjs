import { buildFigure, auditFigure } from "./figures.mjs";
import { writeFileSync } from "node:fs";

const objectName = process.argv[2] || "windmill";
const aspect = process.argv[3] || "16:9";
const outPath = process.argv[4];

const fig = buildFigure(objectName, aspect);
const res = auditFigure(fig);

if (outPath) {
  writeFileSync(outPath, JSON.stringify({ passed: res.failures === 0, failures: res.failures, report: res.report }, null, 2), "utf-8");
}

console.log(`Audit ${objectName} ${aspect}: ${res.failures === 0 ? "PASSED" : `FAILED (${res.failures} problems)`}`);
if (res.failures > 0) {
  console.log(res.report);
  process.exit(1);
}
