#!/usr/bin/env python3
"""Retry failed USPS FAQ article pages."""

import json
import time
import urllib.request
import urllib.error

API_KEY = "fc-856489437f184451a5ce9611048ef89c"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"
OUTPUT_FILE = "/Users/RujutaGandhi/rujutagandhi.github.io/usps-chatbot/usps_raw.json"

with open(OUTPUT_FILE) as f:
    data = json.load(f)

failed_urls = [r["url"] for r in data.get("failed", [])]
print(f"Retrying {len(failed_urls)} failed URLs (sequential, 1s delay)...")

newly_scraped = []
still_failed = []

for i, url in enumerate(failed_urls, 1):
    payload = json.dumps({
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
    }).encode()
    try:
        req = urllib.request.Request(SCRAPE_URL, data=payload, headers=HEADERS, method="POST")
        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read())
        if result.get("success"):
            newly_scraped.append({"url": url, "data": result.get("data", {})})
            if i % 10 == 0:
                print(f"[{i}/{len(failed_urls)}] OK: {url}")
        else:
            still_failed.append({"url": url, "error": result.get("error", "unknown")})
            print(f"[{i}/{len(failed_urls)}] FAILED: {url}")
    except Exception as e:
        still_failed.append({"url": url, "error": str(e)})
        print(f"[{i}/{len(failed_urls)}] ERROR: {url} - {e}")
    time.sleep(1.0)

print(f"\nRetry done: {len(newly_scraped)} recovered, {len(still_failed)} still failed.")

# Merge into output
data["pages"].extend(newly_scraped)
data["failed"] = still_failed
data["total_pages"] = len(data["pages"])
data["scraped_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

with open(OUTPUT_FILE, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Updated usps_raw.json: {data['total_pages']} pages, {len(still_failed)} still failed.")
