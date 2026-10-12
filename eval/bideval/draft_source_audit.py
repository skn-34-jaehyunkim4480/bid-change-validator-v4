"""Source-grounded DRAFT coverage audit: never an approved Golden/model score.

No database, network, extractor, or LLM access. Reuses the existing real dataset
and Core's selection/chunking functions. A draft's completeness is not assumed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bidengine.document.backend_blocks import canonical_source_blocks
from bideval.real_adapter import load_real_cases
from bideval.runner import chunk_and_select
from bideval.scoring import context_chunks, score_case


def _compact(value: str) -> str:
    return "".join(value.split())


def _matches(quote: str, chunks: list[dict], document_key: str) -> bool:
    return any(
        any(block.get("document_id") == "dataset:" + document_key for block in c["source_blocks"])
        and _compact(quote) in _compact(c["text"])
        for c in chunks
    )


def inspect_draft_label(label: dict, documents: dict[str, dict], selected: list[dict]) -> dict:
    """Require verbatim draft grounding at the *claimed* source block location."""
    key = label["document_key"]
    if key not in documents:
        raise ValueError(f"Unknown draft document key: {key}")
    doc = documents[key]
    if label.get("document_name") != doc["name"]:
        raise ValueError(f"Draft document name mismatch: {label['label_id']}")
    loc = label["location"]
    first, last = loc["block_start"], loc["block_end"]
    blocks = doc["extracted_blocks"]
    if (type(first) is not int or type(last) is not int
            or first < 0 or first > last or last >= len(blocks)):
        raise ValueError(f"Draft block range invalid: {label['label_id']}")
    chosen = blocks[first:last + 1]
    if any(b.get("block_index") != i for i, b in enumerate(chosen, first)):
        raise ValueError(f"Draft block indices inconsistent: {label['label_id']}")
    if (chosen[0].get("section_index") != loc["section_index"]
            or chosen[0].get("paragraph_index") != loc["paragraph_start"]
            or chosen[-1].get("paragraph_index") != loc["paragraph_end"]):
        raise ValueError(f"Draft source coordinates mismatch: {label['label_id']}")
    quote = label["raw"]
    if not _compact(quote) or _compact(quote) not in _compact("\n".join(b["text"] for b in chosen)):
        raise ValueError(f"Draft quote not grounded at claimed blocks: {label['label_id']}")
    return {"label_id": label["label_id"], "document_key": key,
            "block_start": first, "block_end": last,
            "candidate_type": (label.get("canonical_candidate") or {}).get("type"),
            "source_grounded": True,
            "selected": _matches(quote, selected, key)}


def audit_dataset(real_root: Path, draft_file: Path) -> dict:
    """Report only source-grounded provisional coverage; never infer P/R/F1."""
    draft = json.loads(draft_file.read_text(encoding="utf-8"))
    if (draft.get("status") != "DRAFT" or draft.get("evaluation_eligible") is not False
            or any(label.get("review_decision") != "PENDING"
                   for label in draft.get("source_requirements", []))):
        raise ValueError("Only pending, evaluation-ineligible DRAFT labels are supported")
    labels = draft.get("source_requirements", [])
    ids = [label["label_id"] for label in labels]
    if not labels or len(ids) != len(set(ids)):
        raise ValueError("Draft labels must have unique nonempty IDs")

    cases = load_real_cases(real_root, ("C01", "G2", "C04", "C02", "C03"))
    results = []
    selected_by_version = {}
    for case in cases:
        blocks = [canonical_source_blocks(
            document_id=doc["document_id"] or "dataset:" + doc["document_key"], blocks=doc["extracted_blocks"],
            file_sha256=doc["source_file_sha256"], text_sha256=doc["extracted_text_sha256"])
            for doc in case.documents]
        chunks, selected = chunk_and_select(blocks)
        selected_by_version[(case.spec.case_id, case.version.version_key)] = selected
        context = score_case([], chunks, selected)["context"]
        results.append({"case_id": case.spec.case_id, "notice_no": case.spec.notice_no,
                        "version_key": case.version.version_key,
                        "documents": len(case.documents), "selected_chunks": len(selected),
                        "context_full_chars": context["full_chars"],
                        "context_truncated_chars": context["truncated_chars"]})

    target = next((c for c in cases if c.spec.case_id == draft.get("case_id")
                   and c.version.version_key == draft.get("version_key")), None)
    if target is None or target.spec.notice_no != draft.get("notice_no"):
        raise ValueError("Draft notice/version identity does not match real dataset")
    source_by_key = {d.document_key: d for d in target.spec.documents}
    documents = {d["document_key"]: {**d, "name": source_by_key[d["document_key"]].name}
                 for d in target.documents}
    selected = selected_by_version[(target.spec.case_id, target.version.version_key)]
    rows = [inspect_draft_label(label, documents, selected) for label in labels]
    visible = context_chunks(selected)
    for row, label in zip(rows, labels):
        row["in_32k_context"] = _matches(label["raw"], visible, label["document_key"])

    obs_file = real_root / "cases/G2/observations/source-change.json"
    obs = json.loads(obs_file.read_text(encoding="utf-8"))
    if obs.get("review_status") != "DRAFT" or obs.get("not_ground_truth") is not True:
        raise ValueError("G2 observation must remain an unapproved draft")
    before_selected = selected_by_version[("G2", "G2-v1")]
    g2_before = next(c for c in cases if c.spec.case_id == "G2" and c.version.version_key == "G2-v1")
    g2_after = next(c for c in cases if c.spec.case_id == "G2" and c.version.version_key == "G2-v2")
    before_docs = {d["document_id"]: d for d in g2_before.documents}
    after_docs = {d["document_id"]: d for d in g2_after.documents}
    if (obs["baseline_version_id"] != str(g2_before.version.notice_version_id)
            or obs["current_version_id"] != str(g2_after.version.notice_version_id)
            or obs["baseline_document_id"] not in before_docs
            or obs["current_document_id"] not in after_docs
            or set(obs["current_checked_document_ids"]) != set(after_docs)):
        raise ValueError("G2 observation provenance does not match checked versions/documents")
    source_block = before_docs[obs["baseline_document_id"]]["extracted_blocks"][obs["location"]["block_index"]]
    if (source_block.get("page") != obs["location"]["page"]
            or _compact(obs["quote"]) not in _compact(source_block["text"])):
        raise ValueError("G2 observation quote is not at its claimed original page/block")
    baseline_present = any(_compact(obs["quote"]) in _compact(d["extracted_text"])
                           for d in g2_before.documents)
    before_selected_present = any(_compact(obs["quote"]) in _compact(c["text"]) for c in before_selected)
    current_exact_absent = not any(_compact(obs["quote"]) in _compact(d["extracted_text"])
                                   for d in g2_after.documents)
    return {
        "evaluation_status": "DRAFT_ONLY_NOT_APPROVED",
        "internal_dataset_hashes_verified": True,
        "extractor_calls": 0,
        "model_requirement_precision": None, "model_requirement_recall": None,
        "model_requirement_f1": None, "evidence_match_rate": None,
        "wrong_final_verdicts": None,
        "versions": results,
        "draft_source_labels": len(rows),
        "draft_source_grounded": sum(r["source_grounded"] for r in rows),
        "draft_selected": sum(r["selected"] for r in rows),
        "draft_in_32k_context": sum(r["in_32k_context"] for r in rows),
        "draft_selection_coverage": sum(r["selected"] for r in rows) / len(rows),
        "draft_context_coverage": sum(r["in_32k_context"] for r in rows) / len(rows),
        "draft_labels": rows,
        "g2_draft_change": {"notice_no": "R26BK01686455",
                            "baseline_quote_present": baseline_present,
                            "baseline_quote_selected": before_selected_present,
                            "current_exact_quote_absent": current_exact_absent,
                            "semantic_removal_approved": False,
                            "reuse_retire_eligibility_verified": False},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit_dataset(args.dataset, args.draft), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
