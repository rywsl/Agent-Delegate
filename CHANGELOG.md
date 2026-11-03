# Changelog

## 0.2.0

- Removed billing, balances, top-ups, per-task gateway tokens and the `new-api` sidecar.
- Added direct OpenAI, Anthropic and Gemini official Python SDK execution with tool loops and token auditing.
- Added encrypted provider API keys, custom Base URLs and enable controls in the admin console.
- Added user-configurable provider, model, sandbox and harness defaults.
- Added optional Claude Code, Codex, Gemini, Grok, Pi and DeepSeek harness adapters without installing external CLIs in the default image.
- Preserved MCP task delegation, uploads, patches, output files and audit trails.
- Added non-destructive database upgrades for the new execution settings.
