#!/usr/bin/env node
// Thin CLI shim around openapi-mcp-generator's programmatic getToolsFromOpenApi()
// (vendored in ./openapi-mcp-generator/) — invoked as a subprocess from
// orchestrate/onboarding/wrapper_generator.py's synthesize_openapi_action,
// since that library is TypeScript/Node and this project's backend is
// Python. Prints the resulting McpToolDefinition[] as JSON to stdout;
// prints a JSON {"error": ...} to stderr and exits 1 on failure.

import { getToolsFromOpenApi } from "./openapi-mcp-generator/dist/index.js";

const [, , specPathOrUrl, baseUrlArg] = process.argv;
if (!specPathOrUrl) {
  console.error(JSON.stringify({ error: "usage: get_tools_shim.mjs <specPathOrUrl> [baseUrl]" }));
  process.exit(2);
}

const options = {};
if (baseUrlArg) options.baseUrl = baseUrlArg;

try {
  const tools = await getToolsFromOpenApi(specPathOrUrl, options);
  process.stdout.write(JSON.stringify(tools));
} catch (err) {
  console.error(JSON.stringify({ error: String((err && err.message) || err) }));
  process.exit(1);
}
