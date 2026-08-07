# Vendored: openapi-mcp-generator

`openapi-mcp-generator/` is a vendored copy of
[harsha-iiiv/openapi-mcp-generator](https://github.com/harsha-iiiv/openapi-mcp-generator)
v4.0.1 (MIT license — see `openapi-mcp-generator/LICENSE`), used by
`orchestrate/onboarding/wrapper_generator.py`'s OpenAPI track for real
per-operation parameter/request-body schema extraction that
`inspector.py`'s lightweight direct spec parse can't do.

`get_tools_shim.mjs` is a thin CLI wrapper around its programmatic
`getToolsFromOpenApi()` API, invoked as a subprocess from Python (this
project's backend is Python; that library is TypeScript/Node — genuine
cross-language infra, not hidden from callers, who must check
`shutil.which("node")` themselves first).

## One-time setup (not automatic — matches this repo's own `alembic
upgrade head` convention of deliberate, documented setup steps rather than
running automatically on boot)

Requires Node >= 20.

```bash
cd orchestrate/onboarding/vendor/openapi-mcp-generator
npm install
npm run build
```

`node_modules/` and `dist/` are gitignored (root `.gitignore`'s existing
`dist/`/`node_modules/` patterns) — rebuilt fresh via the two commands
above, not committed.

## Keeping this current

If updating: re-copy `src/`, `bin/`, `package.json`, `package-lock.json`,
`tsconfig.json`, `LICENSE`, `README.md` from the upstream repo, run
`npm audit fix` (the initial vendoring found and fixed real runtime-path
vulnerabilities in `fast-uri`/`js-yaml`/`path-to-regexp`/`qs` — always
re-check before treating a new vendor drop as done), then `npm install &&
npm run build` again.
