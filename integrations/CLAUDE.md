# integrations/

Runtime-agnostic wrapper for external tool/agent integration.

## Files

| File | Lines | Role |
|---|---|---|
| `tool.py` | 53 | `analyze_repository(...)` → `{"ok": True, "analysis": {...}}` or `{"ok": False, "error": {...}}`. Never raises for expected errors. |
| `tool-schema.json` | 28 | OpenAI-compatible function tool schema for `analyze_repository` |
