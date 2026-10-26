import json, sys
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import router
import app.config as config
app = FastAPI(); app.include_router(router)
c = TestClient(app)
print("db", config.DB_PATH)
for nid in (2435, 2458):
    r = c.get(f"/api/news/{nid}")
    body = r.json()
    print(nid, r.status_code, body.get("source", {}).get("name"), body.get("title"))
    print("  ai =", json.dumps(body.get("ai"), ensure_ascii=False))
