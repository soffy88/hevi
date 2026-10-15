
import { generateFigureHtml } from "/data/soffy/projects/hevi-anatomy/hevi/capabilities/anatomy_explainer/figures.mjs";
import { existsSync } from "node:fs";
generateFigureHtml("clock_gear", "16:9", 42, "/data/soffy/projects/hevi-anatomy/audit/anatomy/samples/clock_gear_16_9/anatomy_clock_gear_16_9.html");
