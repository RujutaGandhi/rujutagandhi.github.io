#!/usr/bin/env python3
"""Scrape all USPS FAQ article pages and save as usps_raw.json."""

import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

API_KEY = "fc-856489437f184451a5ce9611048ef89c"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"

with open("/tmp/usps_article_urls.json") as f:
    article_urls = json.load(f)

print(f"Scraping {len(article_urls)} article pages...")

results = []
failed = []

def scrape_page(url):
    payload = json.dumps({
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
    }).encode()
    try:
        req = urllib.request.Request(SCRAPE_URL, data=payload, headers=HEADERS, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        if data.get("success"):
            return {"url": url, "data": data.get("data", {})}
        else:
            return {"url": url, "error": data.get("error", "unknown")}
    except Exception as e:
        return {"url": url, "error": str(e)}

# Also include topic catalog page from the initial crawl
topic_catalog = {
    "url": "https://faq.usps.com/s/topiccatalog",
    "data": {
        "markdown": "See topic catalog for full list of topics.",
        "metadata": {"title": "Topic Catalog", "sourceURL": "https://faq.usps.com/s/topiccatalog"}
    }
}
results.append(topic_catalog)

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(scrape_page, url): url for url in article_urls}
    completed = 0
    for future in as_completed(futures):
        result = future.result()
        completed += 1
        if "error" in result:
            failed.append(result)
            print(f"[{completed}/{len(article_urls)}] FAILED: {result['url']} - {result['error']}")
        else:
            results.append(result)
            if completed % 20 == 0:
                print(f"[{completed}/{len(article_urls)}] scraped so far...")

print(f"\nDone. {len(results)} pages scraped, {len(failed)} failed.")

output = {
    "source": "https://faq.usps.com/s/topiccatalog",
    "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "total_pages": len(results),
    "pages": results,
    "failed": failed,
}

with open("/Users/RujutaGandhi/rujutagandhi.github.io/usps-chatbot/usps_raw.json", "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Saved to usps_raw.json")
