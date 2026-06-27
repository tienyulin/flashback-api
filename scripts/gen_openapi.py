#!/usr/bin/env python3
"""pre-commit hook: regenerate openapi.json from the app's code — stdlib only.

The OpenAPI spec is generated FROM your code (routes/params/Pydantic models), so
this keeps committed openapi.json always in sync. Import the app object and call
.openapi(); no server needed.

Usage (in .pre-commit-config.yaml, see docs/guides/authoring-source-docs.md):
  entry: python scripts/gen_openapi.py --app app.main:app
or set env APP_MODULE=app.main:app. Output defaults to ./openapi.json.

If the target isn't importable or has no .openapi() (not FastAPI / can't produce
a spec), exit 0 WITHOUT writing — this hook simply doesn't apply (use Mode B,
hand-written markdown). It never blocks a commit for that reason.
"""
import argparse
import importlib
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default=os.environ.get("APP_MODULE", "app.main:app"),
                    help="ASGI app target as module:attr (uvicorn style)")
    ap.add_argument("--out", default="openapi.json")
    args = ap.parse_args()

    if ":" not in args.app:
        print(f"[gen-openapi] --app 需為 module:attr，收到 '{args.app}' → 跳過"); return 0
    mod_name, attr = args.app.split(":", 1)
    try:
        mod = importlib.import_module(mod_name)
        app = getattr(mod, attr)
    except Exception as e:
        print(f"[gen-openapi] 無法 import {args.app}（{type(e).__name__}）→ 跳過（走 Mode B 手寫）")
        return 0
    if not hasattr(app, "openapi") or not callable(app.openapi):
        print(f"[gen-openapi] {args.app} 沒有 .openapi()（非 FastAPI/不能產）→ 跳過")
        return 0

    try:
        spec = app.openapi()
    except Exception as e:
        print(f"[gen-openapi] app.openapi() 失敗：{e}")
        return 1
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    print(f"[gen-openapi] 已寫 {args.out}（{len(spec.get('paths', {}))} paths）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
