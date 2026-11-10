#!/usr/bin/env python3
"""Publish every project the local pika knows (this pika exists only to feed the public site)."""
import json, urllib.request
o = urllib.request.build_opener(urllib.request.ProxyHandler({}))
url = "http://127.0.0.1:7171/api/v1/settings/publishing"
for p in json.load(o.open(url))["projects"]:
    if not p["published"]:
        req = urllib.request.Request(url, data=json.dumps({"project": p["project"], "published": True}).encode(),
                                     headers={"Content-Type": "application/json"}, method="PATCH")
        o.open(req)
        print("published project", p["project"])
