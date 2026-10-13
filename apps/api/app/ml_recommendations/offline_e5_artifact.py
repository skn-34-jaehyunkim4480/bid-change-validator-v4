"""Generate locally precomputed E5-small vectors (no AWS model loading).

Query embeddings are usable ONLY when the exact query sha256 matches; changed
company profiles or arbitrary queries must fall back to BM25 on the API host.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .light_retrieval_eval import companies


def query_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def split_passages(row: dict, tokenizer, *, max_tokens=180, max_chunks=8) -> tuple[list[str], bool]:
    """Count title+prefix+body with E5's ACTUAL tokenizer before encoding."""
    title = str(row["title"])
    title_ids = tokenizer.encode(title, add_special_tokens=False)[:60]
    header = "passage: " + tokenizer.decode(title_ids, skip_special_tokens=True) + "\n"
    budget = min(max_tokens, max(60, 240 - len(tokenizer.encode(header, add_special_tokens=False))))
    chunks = []
    source = (row.get("selected_document") or {}).get("excerpts") or []
    texts = [e["text"] for e in source] if source else [title]
    for body in texts:
        tokens = tokenizer.encode(body, add_special_tokens=False)
        for start in range(0, len(tokens), budget):
            piece = tokenizer.decode(tokens[start:start+budget], skip_special_tokens=True)
            entry = header + piece
            # Decode/re-encode can change token boundaries; enforce hard input budget.
            while len(tokenizer.encode(entry, add_special_tokens=False)) > 248:
                piece = piece[:-10]
                entry = header + piece
            chunks.append(entry)
    clipped = len(chunks) > max_chunks
    return chunks[:max_chunks] or [header], clipped


def generate(corpus: list[dict], snapshot: dict, model, *, batch_size=16) -> dict:
    import numpy as np
    model.max_seq_length = 256
    tok = model.tokenizer
    docs = []
    chunk_total = 0
    clipped_docs = 0
    for row in corpus:
        passages, clipped = split_passages(row, tok)
        chunk_total += len(passages)
        clipped_docs += int(clipped)
        chunks = model.encode(passages, batch_size=batch_size,
                              normalize_embeddings=True, convert_to_numpy=True,
                              show_progress_bar=False)
        # Pool passage windows *after* each was encoded, not a 256-token concatenation.
        vector = np.mean(chunks, axis=0)
        vector = vector / max(float(np.linalg.norm(vector)), 1e-12)
        docs.append({"notice_version_id": row["notice_version_id"],
                     "vector": np.round(vector, 6).tolist(),
                     "chunks": len(passages), "clipped": clipped})
    queries = []
    clipped_queries = 0
    for q in companies(snapshot):
        raw = "query: " + q["text"]
        encoded = tok.encode(raw, add_special_tokens=False)
        clipped_queries += int(len(encoded) > 248)
        safe_query = tok.decode(encoded[:248], skip_special_tokens=True)
        vector = model.encode([safe_query], batch_size=1,
                              normalize_embeddings=True, convert_to_numpy=True,
                              show_progress_bar=False)[0]
        queries.append({"company_id": q["id"], "query_sha256": query_hash(q["text"]),
                        "vector": np.round(vector, 6).tolist()})
    return {"schema": "bidcheck-e5-offline-v1",
            "model": "intfloat/multilingual-e5-small", "docs": docs, "queries": queries,
            "document_count": len(docs), "company_query_count": len(queries),
            "document_chunks": chunk_total, "clipped_document_count": clipped_docs,
            "clipped_query_count": clipped_queries,
            "pretrained_frozen_no_finetune": True, "approval": "UNVERIFIED_EXPERIMENT",
            "query_vectors_not_valid_after_profile_edit": True}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--corpus",type=Path,required=True)
    p.add_argument("--snapshot",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--model",default="intfloat/multilingual-e5-small")
    args=p.parse_args()
    if args.out.exists():
        raise FileExistsError("Do not overwrite a frozen vector artifact")
    from sentence_transformers import SentenceTransformer
    import torch
    torch.set_num_threads(min(6,torch.get_num_threads()))
    model=SentenceTransformer(args.model,device="cpu",local_files_only=True,trust_remote_code=False)
    corpus=json.loads(args.corpus.read_text(encoding="utf-8-sig"))
    snapshot=json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
    artifacts=generate(corpus,snapshot,model)
    artifacts["corpus_sha256"]=hashlib.sha256(args.corpus.read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(artifacts,ensure_ascii=False),encoding="utf-8")
    print("OFFLINE_E5_READY",json.dumps({key:artifacts[key] for key in
          ("document_count","company_query_count","document_chunks","clipped_document_count",
           "clipped_query_count",
           "corpus_sha256")},ensure_ascii=False))


if __name__=="__main__":
    main()
