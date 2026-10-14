"""Offline, version-bound task corpus. All selected source text is UNVERIFIED.

No model labels or human approvals are produced here; fallback is always the notice title.
File original SHA and extracted SHA are RDS metadata, not locally verified source bytes.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import re
from pathlib import Path

TASK_NAMES = re.compile(
    r"제안요청서|과업(?:지시|내용|설명)서|시방서|규격서|구매규격|사양서|요구사항|설계서|설명서|"
    r"사업계획서|용역수행|기술제안|물품내역|공사내역", re.I
)
BOILER_NAMES = re.compile(
    r"계약(?:일반|특수)?조건|청렴(?:계약|서약)|입찰(?:유의|참가|공고|안내)|공고문|"
    r"계약예규|유의사항|서약서|각서|서식|공통기준|안전입찰|보증", re.I
)
HEADINGS = re.compile(
    r"사업\s*(?:개요|목적|내용|범위)|과업\s*(?:내용|범위|목적|개요|수행)|"
    r"수행\s*(?:업무|내용|범위)|구축\s*(?:내용|범위|목표)|"
    r"요구\s*(?:사항|기능|성능)|납품\s*(?:물품|규격|범위)|"
    r"장비\s*(?:규격|구성)|제품\s*(?:규격|사양)|공사\s*(?:개요|내용|범위)|"
    r"주요\s*(?:기능|업무|사양)|기술\s*(?:사양|규격)", re.I
)
BOILER_TEXT = re.compile(
    r"입찰참가자격|계약보증금|입찰보증금|계약예규|청렴계약|제출서류|"
    r"개찰일시|낙찰자\s*결정|입찰\s*유의사항|계약일반조건", re.I
)
TOKEN = re.compile(r"[가-힣A-Za-z0-9]+")
# Conservative exclusions for public-notice boilerplate and contents pages.
HARD_BOILER_FILE = re.compile(r"\ud45c\uc900\uacf5\uace0\ubb38|\uacf5\uace0\ubb38|\uacf5\uace0\uc11c|\uacc4\uc57d\uc77c\ubc18\uc870\uac74|\uc785\ucc30\uc548\ub0b4")
CONDITION_PARAGRAPH = re.compile(r"\uc785\ucc30\ucc38\uac00|\uacc4\uc57d\uc0c1\ub300\uc790\uc758\s*\ubd80\ub2f4|\ud3c9\uac00\uc704\uc6d0|\ubd80\uc815\ub2f9|\uc801\uc6a9\ubc95\ub839|\ud22c\ucc30\ubcf4\uc99d|\uc785\ucc30\uc124\uba85|\uac1c\ucc30\uc77c\uc2dc")
TECHNICAL_TERMS = re.compile(r"\uc2dc\uc2a4\ud15c|\uc778\ud130\ud398\uc774\uc2a4|\uad6c\ud604|\uac1c\ubc1c|\uad6c\ucd95|\uae30\ub2a5|\uc131\ub2a5|\uc5f0\ub3d9|\ub370\uc774\ud130|\uc7a5\ube44|\uaddc\uaca9|\uc0ac\uc591|\uc124\uce58|\uc2dc\uacf5|\ub0a9\ud488|\ubb3c\ud488|\uacf5\uc0ac|\uc81c\uc791|\uce21\uc815|\uc218\ub7c9|\ucc98\ub9ac|\uc218\ud589|interface|specification|optical|measurement|software|RS-232|USB|LIMS",re.I)
TOC_PAGE = re.compile(r"\b\d{1,3}\s*/")

MAX_EXCERPTS = 3
MAX_CHARS = 1600


def document_priority(doc: dict) -> tuple[int, int, str]:
    name = str(doc.get("name") or "")
    if HARD_BOILER_FILE.search(name) and not TASK_NAMES.search(name):
        rank = 3
    elif BOILER_NAMES.search(name) and not TASK_NAMES.search(name):
        rank = 3
    elif BOILER_NAMES.search(name):
        rank = 2
    elif TASK_NAMES.search(name):
        rank = 0
    else:
        rank = 1
    # Prefer short, human-readable task attachments before huge boilerplate.
    chars = min(int(doc.get("extracted_char_count") or 0), 350000)
    return (rank, -chars, str(doc.get("document_id") or doc.get("id") or ""))


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def select_scope_blocks(doc: dict) -> dict:
    """Return bounded excerpts, original block indices and *heuristic* status."""
    if document_priority(doc)[0] == 3:
        return {"status": "NO_RELIABLE_TASK_SOURCE", "excerpts": [], "excerpt_sha256": None}
    blocks = doc.get("extracted_blocks") or []
    if not isinstance(blocks, list):
        raise ValueError("extracted_blocks must be a list")
    if len(blocks) > 100000:
        raise ValueError("unbounded extracted_blocks")
    viable = []
    for pos, row in enumerate(blocks):
        if not isinstance(row, dict):
            continue
        raw = _text(row.get("text"))
        if len(raw) < 24 or BOILER_TEXT.search(raw[:85]) or CONDITION_PARAGRAPH.search(raw[:150]):
            continue
        if len(TOC_PAGE.findall(raw)) >= 4 or raw.count("........") > 3:
            continue
        idx = row.get("block_index", pos)
        if not isinstance(idx, int):
            continue
        strong = bool(HEADINGS.search(raw[:200]))
        # Avoid table-of-contents bullets; do not blindly concatenate long documents.
        if raw.count("........") > 3 or raw.count("···") > 6:
            continue
        technical = len(TECHNICAL_TERMS.findall(raw[:500]))
        score = 10 if strong else 0
        score += min(technical, 4) * 2
        score += 3 if TASK_NAMES.search(str(doc.get("name") or "")) else 0
        score += min(len(raw), 320) / 130
        if len(raw) <= 55 and not strong:
            score -= 4
        viable.append((score, pos, idx, raw, strong, technical))
    ranked = sorted(viable, key=lambda r: (-r[0], r[1]))
    picked = []
    positions: set[int] = set()
    for score, pos, idx, text, strong, technical in ranked:
        if any(abs(pos - used) < 2 for used in positions):
            continue
        if score < 5:
            break
        # A task heading alone inside a generic notice is not a reliable scope.
        if not (technical >= 2 or (strong and technical >= 1)):
            continue
        positions.add(pos)
        picked.append({"block_index": idx, "text": text[:MAX_CHARS],
                       "heading_found": strong, "technical_terms": technical,
                       "score": round(score, 2)})
        if len(picked) >= MAX_EXCERPTS:
            break
    picked.sort(key=lambda r: r["block_index"])
    text = "\n".join(p["text"] for p in picked)
    strong = any(p["heading_found"] for p in picked)
    name_good = document_priority(doc)[0] == 0
    # Weak content and non-task titles can be used diagnostically but never verified.
    status = ("TASK_CANDIDATE_UNVERIFIED" if picked and (strong or name_good)
              else "NO_RELIABLE_TASK_SOURCE")
    return {
        "status": status,
        "excerpts": picked if status == "TASK_CANDIDATE_UNVERIFIED" else [],
        "excerpt_sha256": sha256(text.encode("utf-8")).hexdigest() if status == "TASK_CANDIDATE_UNVERIFIED" else None,
    }


def build_corpus(snapshot: dict, metadata: list[dict], excerpts: list[dict]) -> tuple[list[dict], dict]:
    """Join by *exact version_id AND document_id*, never by loose notice number."""
    versions = {n["notice_version_id"]: n for n in snapshot["notices"]}
    if len(versions) != len(snapshot["notices"]):
        raise ValueError("duplicate frozen notice version")
    by_version: dict[str, list[dict]] = {}
    unique_docs = set()
    for doc in metadata:
        vid = str(doc["version_id"])
        did = str(doc["document_id"])
        if (vid, did) in unique_docs:
            raise ValueError("duplicate version-bound document")
        unique_docs.add((vid, did))
        if vid in versions:
            by_version.setdefault(vid, []).append(doc)
    by_source = {}
    for e in excerpts:
        key = (str(e["version_id"]), str(e["document_id"]))
        if key in by_source:
            raise ValueError("duplicate selected document extraction")
        if key not in unique_docs:
            raise ValueError("cross-version or unknown excerpt")
        by_source[key] = e
    rows = []
    counts = Counter()
    for vid, notice in versions.items():
        selected = None
        reason = "no_extracted_document"
        for doc in sorted(by_version.get(vid, []), key=document_priority):
            src = by_source.get((vid, str(doc["document_id"])))
            if src is None:
                reason = "source_not_inspected"
                continue
            candidate = select_scope_blocks({**doc, "extracted_blocks": src.get("extracted_blocks", [])})
            if candidate["status"] == "TASK_CANDIDATE_UNVERIFIED":
                selected = {
                    "document_id": str(doc["document_id"]),
                    "name": doc.get("name"),
                    "file_sha256_metadata": doc.get("file_sha256"),
                    "extracted_sha256_metadata": doc.get("extracted_text_sha256"),
                    **candidate,
                }
                break
            reason = "no_task_excerpt"
        title = str(notice["title"])
        candidate_text = "\n".join(x["text"] for x in selected["excerpts"]) if selected else ""
        # Document chunks stay individually embeddable; no E5 >256-token overflow.
        chunks = [f"passage: {title}\n{x['text'][:600]}" for x in selected["excerpts"]] if selected else [f"passage: {title}"]
        rows.append({
            "notice_id": notice["notice_id"], "notice_version_id": vid,
            "title": title, "posted_at": notice.get("posted_at"),
            "bid_closed_at": notice.get("bid_closed_at"),
            "business_type": notice.get("business_type"),
            "search_text": (title + "\n" + candidate_text).strip(),
            "passages": chunks,
            "selected_document": selected,
            "source_status": selected["status"] if selected else "TITLE_FALLBACK",
            "fallback_reason": None if selected else reason,
            "label_status": "NO_INDEPENDENT_TASK_REVIEW",
        })
        counts[rows[-1]["source_status"]] += 1
    result = {"notice_versions": len(rows),
              "extracted_documents_in_universe": len(unique_docs),
              "inspected_docs": len(by_source),
              "statuses": dict(counts), "human_approved": False,
              "full_task_accuracy": "NOT_MEASURED",
              "source_file_hashes": "RDS_METADATA_ONLY_UNVERIFIED",
              "candidate_scope": "FROZEN_UNIVERSE_NOT_LIVE_VALIDITY"}
    return rows, result


def save_corpus(snapshot: dict, metadata: list[dict], excerpts: list[dict], output: Path) -> dict:
    rows, report = build_corpus(snapshot, metadata, excerpts)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    report["corpus_sha256"] = sha256(output.read_bytes()).hexdigest()
    return report
