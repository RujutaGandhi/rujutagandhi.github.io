#!/usr/bin/env python3
"""Clean usps_raw.json: strip nav boilerplate, keep article body. Output usps_cleaned.json."""

import json
import re

HERO_MARKER = "![](https://faq.usps.com/file-asset/FAQHero?v=1)"

def clean_markdown(md):
    # 1. Strip header boilerplate — everything up to and including the hero image
    idx = md.find(HERO_MARKER)
    if idx != -1:
        md = md[idx + len(HERO_MARKER):].lstrip()

    # 2. Remove the [Share via email] line
    md = re.sub(r'^\[Share via email\]\(mailto:[^\)]*\)\n+', '', md)

    # 3. Strip footer boilerplate — "Customer Information 2" onward is all empty metadata
    md = re.sub(r'\n\nCustomer Information 2\b.*', '', md, flags=re.DOTALL)

    # 4. Strip Related / Trending Articles sections
    md = re.sub(r'\n\n## Related Articles\b.*', '', md, flags=re.DOTALL)
    md = re.sub(r'\n\n## Trending Articles\b.*', '', md, flags=re.DOTALL)

    # 5. Strip trailing "Loading\n\nTitle" echo at the very end
    md = re.sub(r'\n\nLoading\n\n.*$', '', md, flags=re.DOTALL)

    # 6. Strip the metadata block: "Title\n\nXxx\n\nURL Name\n\nXxx" near the end
    md = re.sub(r'\n\nTitle\n\n.*', '', md, flags=re.DOTALL)

    # 7. Strip breadcrumb topic links at the end (lines that are only faq.usps.com/s/topic links)
    md = re.sub(r'\n\n(\[.*?/s/topic/.*?\])+\s*$', '', md, flags=re.DOTALL)

    return md.strip()


def extract_title(md, metadata):
    # Prefer metadata title
    title = (metadata or {}).get("title", "").strip()
    if title and title not in ("Topic Catalog", ""):
        return title
    # Fall back to first ## heading in cleaned markdown
    m = re.search(r'^## (.+)$', md, re.MULTILINE)
    return m.group(1).strip() if m else ""


with open("usps_raw.json") as f:
    raw = json.load(f)

cleaned_pages = []
skipped = 0

for page in raw["pages"]:
    url = page["url"]
    data = page.get("data", {})
    md = data.get("markdown", "")
    metadata = data.get("metadata", {})

    # Skip non-article pages (topic catalog)
    if "/article/" not in url:
        skipped += 1
        continue

    content = clean_markdown(md)
    title = extract_title(content, metadata)

    if not content:
        skipped += 1
        continue

    cleaned_pages.append({
        "url": url,
        "title": title,
        "content": content,
    })

output = {
    "source": raw["source"],
    "scraped_at": raw["scraped_at"],
    "total_pages": len(cleaned_pages),
    "pages": cleaned_pages,
}

with open("usps_cleaned.json", "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Done. {len(cleaned_pages)} articles cleaned, {skipped} skipped.")
print(f"Saved to usps_cleaned.json")
