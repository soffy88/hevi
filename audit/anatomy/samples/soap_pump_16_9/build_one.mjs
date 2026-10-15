
import { generateFigureHtml } from "/data/soffy/projects/hevi-anatomy/hevi/capabilities/anatomy_explainer/figures.mjs";
import { existsSync } from "node:fs";
generateFigureHtml("soap_pump", "16:9", 42, "/data/soffy/projects/hevi-anatomy/audit/anatomy/samples/soap_pump_16_9/anatomy_soap_pump_16_9.html");
