
import { generateFigureHtml } from "/data/soffy/projects/hevi-anatomy/hevi/capabilities/anatomy_explainer/figures.mjs";
import { existsSync } from "node:fs";
generateFigureHtml("waterwheel", "16:9", 42, "/data/soffy/projects/hevi-anatomy/audit/anatomy/samples/waterwheel_16_9/anatomy_waterwheel_16_9.html");
