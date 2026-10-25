"use strict";

const http = require("http");
const https = require("https");

function workbenchUrl(api) {
  const configured = api && api.pluginConfig && api.pluginConfig.baseUrl;
  return String(configured || process.env.CALICLAW_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
}

function callWorkbench(base, method, path, body) {
  const url = new URL(base + path);
  const payload = body ? JSON.stringify(body) : null;
  const lib = url.protocol === "https:" ? https : http;
  return new Promise((resolve, reject) => {
    const req = lib.request(
      url,
      {
        method,
        headers: payload
          ? { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) }
          : {},
      },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          let data = text;
          try {
            data = JSON.parse(text);
          } catch (_) {
            /* keep text */
          }
          resolve({ status: res.statusCode || 0, data });
        });
      },
    );
    req.setTimeout(15000, () => req.destroy(new Error("Workbench request timed out.")));
    req.on("error", reject);
    if (payload) req.write(payload);
    req.end();
  });
}

function textResult(value) {
  return { content: [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value) }] };
}

module.exports = {
  id: "caliclaw",
  name: "CaliClaw",
  description: "Read, prepare, and remember a 3D print. Hardware start and cancel stay on the workbench.",
  register(api) {
    if (api.registrationMode && !["full", "discovery", "tool-discovery"].includes(api.registrationMode)) return;
    const base = workbenchUrl(api);
    api.registerTool(
      {
        name: "caliclaw",
        label: "CaliClaw",
        description:
          "Workshop memory for one printed part. Actions: printers, status, project, revisions, fit, slice. " +
          "fit records a measurement and the features that must stay. " +
          "This tool does not start, pause, or cancel a printer.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            action: {
              type: "string",
              enum: ["printers", "status", "project", "revisions", "fit", "slice"],
              description: "printers lists saved connections and their capabilities. Setup and selection stay on the workbench. status reads the selected printer. project and revisions read the part. fit records a measurement. slice prepares G-code.",
            },
            note: { type: "string", description: "What the printed part did, for action=fit." },
            measured: {
              type: "object",
              description: "Named measurements, for action=fit. Example: {\"usb_x_mm\": 18}.",
            },
            keep: {
              type: "array",
              items: { type: "string" },
              description: "Features that must not change, for action=fit.",
            },
          },
          required: ["action"],
        },
        execute: async (_toolCallId, params) => {
          const action = params && params.action;
          if (action === "start" || action === "pause" || action === "cancel") {
            return textResult({
              ok: false,
              error: "Printer motion stays on the workbench and needs an explicit confirm.",
            });
          }
          try {
            if (action === "printers") return textResult(await callWorkbench(base, "GET", "/api/printers"));
            if (action === "status") return textResult(await callWorkbench(base, "GET", "/api/printer"));
            if (action === "project") return textResult(await callWorkbench(base, "GET", "/api/project"));
            if (action === "revisions") return textResult(await callWorkbench(base, "GET", "/api/revisions"));
            if (action === "fit") {
              return textResult(
                await callWorkbench(base, "POST", "/api/fit", {
                  note: params.note || "",
                  measured: params.measured || {},
                  keep: params.keep || [],
                }),
              );
            }
            if (action === "slice") return textResult(await callWorkbench(base, "POST", "/api/slice"));
            return textResult({ ok: false, error: "unknown action" });
          } catch (err) {
            return textResult({ ok: false, error: err && err.message ? err.message : String(err) });
          }
        },
      },
      { name: "caliclaw" },
    );
  },
};
