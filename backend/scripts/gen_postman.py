"""Generate a Postman collection from the live OpenAPI schema (always in sync with the code)."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from datetime import datetime, timedelta, timezone

from app.main import app

spec = app.openapi()
NOW = datetime.now(timezone.utc).replace(microsecond=0, minute=0, second=0)


def resolve(s):
    while "$ref" in s:
        s = spec["components"]["schemas"][s["$ref"].split("/")[-1]]
    return s


def example(s, name=""):
    s = resolve(s)
    for k in ("anyOf", "oneOf"):
        if k in s:
            opts = [o for o in s[k] if resolve(o).get("type") != "null"]
            return example(opts[0], name) if opts else None
    if "allOf" in s:
        return example(s["allOf"][0], name)
    if "default" in s and s["default"] is not None:
        return s["default"]
    if "enum" in s:
        return s["enum"][0]
    t = s.get("type")
    if t == "object":
        req = set(s.get("required", []))
        return {k: example(v, k) for k, v in s.get("properties", {}).items() if k in req}
    if t == "array":
        return []
    if t == "integer":
        return 1
    if t == "boolean":
        return False
    if t == "string":
        f = s.get("format")
        if f == "date-time":
            return (NOW + timedelta(days=2, hours=2 if name.startswith("end") else 0)).isoformat()
        if f == "email" or name == "email":
            return "user@example.com"
        return {"password": "Passw0rd!x", "username": "jdoe", "refresh_token": "{{refresh_token}}"}.get(name, f"sample {name}".strip())
    return None


folders = {}
for path, methods in spec["paths"].items():
    for method, op in methods.items():
        tag = (op.get("tags") or ["Other"])[0]
        url = "{{base_url}}" + path.replace("{", ":").replace("}", "")
        qs = [p for p in op.get("parameters", []) if p["in"] == "query"]
        req = {
            "method": method.upper(), "header": [{"key": "Content-Type", "value": "application/json"}],
            "url": {"raw": url, "host": ["{{base_url}}"], "path": [x for x in path.replace("{", ":").replace("}", "").split("/") if x],
                    "variable": [{"key": p["name"], "value": "1"} for p in op.get("parameters", []) if p["in"] == "path"],
                    "query": [{"key": p["name"], "value": "", "disabled": True} for p in qs]},
            "description": op.get("summary", ""),
        }
        if path.startswith("/api/auth/") and path.split("/")[-1] in ("register", "login", "refresh"):
            req["auth"] = {"type": "noauth"}
        body = op.get("requestBody", {}).get("content", {})
        if "application/json" in body:
            req["body"] = {"mode": "raw", "raw": json.dumps(example(body["application/json"]["schema"]), indent=2), "options": {"raw": {"language": "json"}}}
        elif "multipart/form-data" in body:
            req["header"] = []
            req["body"] = {"mode": "formdata", "formdata": [{"key": "file", "type": "file"}, {"key": "event_id", "value": "1", "type": "text"}, {"key": "entity_type", "value": "event", "type": "text"}]}
        item = {"name": f"{method.upper()} {path.replace('/api', '')}", "request": req}
        if path == "/api/auth/login":
            item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": [
                "const d = pm.response.json().data;", "if (d) { pm.collectionVariables.set('access_token', d.access_token); pm.collectionVariables.set('refresh_token', d.refresh_token); }"]}}]
        if path == "/api/auth/refresh":
            item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": [
                "const d = pm.response.json().data;", "if (d) { pm.collectionVariables.set('access_token', d.access_token); pm.collectionVariables.set('refresh_token', d.refresh_token); }"]}}]
        folders.setdefault(tag, []).append(item)

coll = {
    "info": {"name": "EventHub API", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
             "description": "Run 'POST /auth/register' then 'POST /auth/login' first; tokens are stored automatically."},
    "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{access_token}}", "type": "string"}]},
    "variable": [{"key": "base_url", "value": "http://localhost:8000"}, {"key": "access_token", "value": ""}, {"key": "refresh_token", "value": ""}],
    "item": [{"name": k, "item": v} for k, v in folders.items()],
}
out = pathlib.Path(__file__).resolve().parents[2] / "postman"
out.mkdir(exist_ok=True)
(out / "EventHub.postman_collection.json").write_text(json.dumps(coll, indent=2))
print("requests:", sum(len(v) for v in folders.values()))
