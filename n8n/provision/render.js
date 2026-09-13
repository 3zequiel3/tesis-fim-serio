#!/usr/bin/env node
/**
 * FIM Platform — n8n workflow templating (D58/RN-152, D44/RN-138, D-6 of the
 * vps-deployment-readiness design).
 *
 * The workflow JSON files checked into `n8n/workflows/` are valid, importable
 * n8n exports. Deployment-specific values that are NOT payload data — the
 * enabled channel set, destination addresses (email to/from, Slack channel,
 * Jira project key, ...) and per-deployment API endpoints used only for
 * testing — are written as `__FIM_ENV_<NAME>__` tokens inside otherwise
 * ordinary JSON string fields, so the checked-in file always stays valid,
 * parseable JSON and the real value never lives in the repository.
 *
 * This script replaces every occurrence of `__FIM_ENV_<NAME>__` in a workflow
 * file's raw text with the current value of `process.env.<NAME>` (empty
 * string when unset), escaping it so it stays valid wherever the token sits —
 * always immediately between two literal `"` characters, whether those are a
 * JSON string's own delimiters or an escaped `\"` pair belonging to a JS
 * string literal nested inside a larger n8n expression. It never adds
 * surrounding quotes itself, so the invariant is a property of the checked-in
 * files, not of this script — see the workflows for examples.
 *
 * Usage: node render.js <input.json> <output.json>
 * Exits non-zero, naming the file, if the rendered output is not valid JSON.
 */
"use strict";

const fs = require("fs");

const TOKEN_RE = /__FIM_ENV_([A-Z0-9_]+)__/g;

function escapeForJsonStringBody(value) {
  // Same escaping JSON.stringify would apply to the *contents* of a string,
  // without the surrounding quotes JSON.stringify also adds.
  return JSON.stringify(String(value)).slice(1, -1);
}

function render(inputPath, outputPath) {
  const raw = fs.readFileSync(inputPath, "utf8");
  const rendered = raw.replace(TOKEN_RE, (_match, name) => {
    const value = process.env[name] ?? "";
    return escapeForJsonStringBody(value);
  });

  try {
    JSON.parse(rendered);
  } catch (err) {
    console.error(`render.js: ${inputPath} did not render to valid JSON: ${err.message}`);
    process.exit(1);
  }

  fs.writeFileSync(outputPath, rendered);
}

function main() {
  const [, , inputPath, outputPath] = process.argv;
  if (!inputPath || !outputPath) {
    console.error("usage: node render.js <input.json> <output.json>");
    process.exit(2);
  }
  render(inputPath, outputPath);
}

main();
