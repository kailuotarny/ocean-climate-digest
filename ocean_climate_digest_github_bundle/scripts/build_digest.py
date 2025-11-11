import os, json, time, datetime, requests, textwrap

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "")

OA_BASE = "https://api.openalex.org"
CR_BASE = "https://api.crossref.org/works"

# ---- Journal whitelist (can edit) ----
JOURNALS = [
    "Nature Geoscience",
    "Nature Climate Change",
    "Communications Earth & Environment",
    "Nature Communications",
    "Science",
    "Science Advances",
    "Proceedings of the National Academy of Sciences",  # PNAS
    "Geology",
    "Geophysical Research Letters",
    "Journal of Geophysical Research: Oceans",
    "Global Biogeochemical Cycles",
    "Paleoceanography and Paleoclimatology",
    "Geochemistry, Geophysics, Geosystems",
    "Earth and Planetary Science Letters",
    "Quaternary Science Reviews",
    "Marine Geology",
    "Deep-Sea Research Part I: Oceanographic Research Papers",
    "Deep-Sea Research Part II: Topical Studies in Oceanography",
    "Ocean Modelling",
    "Progress in Oceanography",
    "Journal of Physical Oceanography",
    "Journal of Climate",
    "Limnology and Oceanography",
    "Ocean Science",
    "Geophysical Journal International",
    "Climate Dynamics"
]

HEADERS = {"User-Agent": f"ocean-digest-bot (mailto:{CONTACT_EMAIL})"} if CONTACT_EMAIL else {}

def taipei_yesterday():
    tz = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(tz)
    y = (now - datetime.timedelta(days=1)).date()
    return y.isoformat()

def get_source_ids(journal_names):
    ids = []
    for name in journal_names:
        # search sources by name; pick first match
        r = requests.get(f"{OA_BASE}/sources", params={"search": name, "per-page": 1}, headers=HEADERS, timeout=30)
        r.raise_for_status()
        res = r.json().get("results", [])
        if res:
            ids.append(res[0]["id"])  # e.g., https://openalex.org/S1983995261
        time.sleep(0.2)
    return ids

def invert_abstract(inv):
    if not inv: return ""
    # OpenAlex abstract is an inverted index {"word": [pos1,pos2,...]}
    arr = []
    for word, poss in inv.items():
        for p in poss:
            if p >= len(arr):
                arr.extend([""] * (p - len(arr) + 1))
            arr[p] = word
    return " ".join(x for x in arr if x)

def fetch_openalex(ydate, source_ids):
    if not source_ids: return []
    ids = "|".join(s.split("/")[-1] for s in source_ids)
    filt = f"type:journal-article,primary_location.source.id:{ids},from_publication_date:{ydate},to_publication_date:{ydate}"
    params = {
        "filter": filt,
        "per-page": 200,
        "select": "id,doi,title,publication_year,publication_date,primary_location,authorships,abstract_inverted_index"
    }
    r = requests.get(f"{OA_BASE}/works", params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json().get("results", [])

def fallback_crossref(ydate):
    # Restrict to our journal names
    items = []
    for j in JOURNALS:
        p = {
            "filter": f"from-pub-date:{ydate},until-pub-date:{ydate},container-title:{j}",
            "rows": 100,
            "select": "DOI,title,container-title,author,issued,URL,type"
        }
        r = requests.get(CR_BASE, params=p, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            for it in r.json().get("message", {}).get("items", []):
                if it.get("type") != "journal-article": continue
                items.append({
                    "doi": it.get("DOI"),
                    "title": (it.get("title") or [""])[0],
                    "venue": (it.get("container-title") or [""])[0],
                    "year": int(str(it.get("issued", {}).get("date-parts", [[None]])[0][0] or "") or 0),
                    "authors": [a.get("family","") + (", " + a.get("given","") if a.get("given") else "") for a in it.get("author", [])][:5],
                    "link": it.get("URL"),
                    "oa": False,
                    "subfield": ""  # filled by LLM
                })
        time.sleep(0.2)
    return items

def to_item(work):
    doi = work.get("doi")
    pl = work.get("primary_location") or {}
    src = (pl.get("source") or {})
    venue = src.get("display_name") or ""
    link = (pl.get("landing_page_url") or pl.get("pdf_url") or "")
    year = work.get("publication_year") or (work.get("publication_date") or "0000")[:4]
    authors = []
    for au in (work.get("authorships") or []):
        name = au.get("author",{}).get("display_name")
        if name: authors.append(name)
    item = {
        "doi": doi,
        "title": work.get("title"),
        "venue": venue,
        "year": int(year) if isinstance(year, int) or (isinstance(year,str) and year.isdigit()) else year,
        "authors": authors[:5],
        "subfield": "",  # filled by LLM
        "summary": "",
        "context": "",
        "open_question": "",
        "link": link or (f"https://doi.org/{doi}" if doi else ""),
        "oa": True if (pl.get("is_oa") or (pl.get("license") and 'cc-' in (pl.get("license") or '').lower())) else False,
        "keywords": []
    }
    # add abstract if available
    abs_text = invert_abstract(work.get("abstract_inverted_index"))
    if abs_text: item["_abstract"] = abs_text
    return item

def llm_enrich(item):
    if not OPENAI_KEY: return item
    content = textwrap.dedent(f"""
    你是一名资深学术编辑，领域：海洋科学/沉积学/古气候/海洋地质/海洋地球物理/海洋物理与化学/海洋生物/气候变化。
    给定论文元数据与摘要，请输出：
    1) 关键结论（1 句，中文，避免夸张辞藻）；
    2) 与以往研究对比（2–3 句，引用 1–2 篇里程碑或近期研究，仅列作者或期刊缩写即可）；
    3) 一个清晰、可检验的未解决科学问题（1 句，中文）。
    4) 给出最可能的子领域标签（八选一：海洋物理学/海洋化学/海洋生物学/海洋地质学/海洋地球物理学/沉积学/古气候学/古海洋学/气候变化科学）。
    仅返回 JSON：{{"summary": "...","context": "...","open_question": "...","subfield":"..."}}。

    元数据：
    标题：{item.get("title")}
    期刊：{item.get("venue")}
    作者：{", ".join(item.get("authors", []))}
    DOI：{item.get("doi")}
    摘要：{item.get("_abstract","(无)")}
    """).strip()

    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role":"system","content":"You are a careful, concise scientific assistant."},
                    {"role":"user","content": content}
                ],
                "temperature": 0.2
            }, timeout=120)
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        data = json.loads(txt)
        item["summary"] = data.get("summary","")
        item["context"] = data.get("context","")
        item["open_question"] = data.get("open_question","")
        item["subfield"] = data.get("subfield","")
    except Exception as e:
        item["summary"] = item.get("_abstract","")[:200] + ("..." if item.get("_abstract") else "")
        item["context"] = "（自动生成失败，保留摘要片段）"
        item["open_question"] = "该研究尚未解决的问题有待随后评估。"
    return item

def main():
    ydate = taipei_yesterday()
    os.makedirs("docs", exist_ok=True)

    # 1) map journal names -> OpenAlex source ids
    sids = get_source_ids(JOURNALS)

    # 2) fetch works from OpenAlex
    works = fetch_openalex(ydate, sids)
    items = [to_item(w) for w in works]

    # 3) fallback: Crossref
    if not items:
        items = fallback_crossref(ydate)

    # 4) dedupe by DOI & cap 25
    seen = set(); clean = []
    for it in items:
        if not it.get("doi"): continue
        k = it["doi"].lower()
        if k in seen: continue
        seen.add(k); clean.append(it)
        if len(clean) >= 25: break

    # 5) LLM enrichment (optional)
    final_items = []
    for it in clean:
        final_items.append(llm_enrich(it))
        time.sleep(0.3)

    # 6) choose 3 must-read (heuristic: prioritize venues & presence of OA)
    top = sorted(final_items, key=lambda x: (x.get("venue","") in {"Nature Geoscience","Nature Climate Change","Science","Nature Communications","Science Advances","PNAS"}, x.get("oa",False)), reverse=True)[:3]
    must = [x.get("doi") for x in top if x.get("doi")]

    data = {
        "date": ydate,
        "items": final_items,
        "must_read": must
    }

    with open("docs/latest.json","w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(f"docs/{ydate}.json","w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Generated docs/latest.json for {ydate} with {len(final_items)} items.")

if __name__ == "__main__":
    main()
