from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import csv
from hashlib import sha256
import json
import pytest
from app.ml_recommendations.alternate_source_review import (
    prepare_alternate_reviews,verify_alternate_review,persist_preview_dev_labels
)

def _sources(tmp_path):
    root=tmp_path/"private"
    root.mkdir()
    targets=[]
    for i in range(8):
        text="This sample describes a concrete construction or delivery scope with explicit requirements "+str(i)
        target={"index":i,"version_id":"v"+str(i),"document_id":"d"+str(i),
                "name":"work_scope"+str(i),"file_sha256":"a"*64,"extracted_text_sha256":"b"*64}
        targets.append(target)
    (root/"alternate_targets_8.json").write_text(json.dumps(targets),encoding="utf-8")
    for j in (0,2,4,6):
        batch=[{"id":f"d{k}","version_id":f"v{k}","name":f"work_scope{k}",
                "file_sha256":"a"*64,"extracted_text_sha256":"b"*64,
                "sample":[{"block_index":10,"text":"Task source includes concrete system or service content for procurement and implementation "+str(k)}]}
               for k in (j,j+1)]
        (root/f"alternate_small_{j}.json").write_text(json.dumps(batch),encoding="utf-8")
    return root

def test_alternate_review_preserves_origin_and_never_auto_approves(tmp_path):
    root=_sources(tmp_path)
    result=prepare_alternate_reviews(root,{i:[10] for i in range(8)},root/"review")
    assert result["recovered_task_excerpt_candidates"]==8
    assert not result["full_task_accuracy_ready"]
    assert verify_alternate_review(root,root/"review")["verified_previews"]==8
    rows=[json.loads(x) for x in (root/"review"/"alternate_review_candidates.jsonl").read_text().splitlines()]
    assert all(x["source_block_text_clipped_to_550_chars"] and not x["human_approved"] for x in rows)

def test_rejects_mismatched_version(tmp_path):
    root=_sources(tmp_path)
    file=root/"alternate_small_0.json"
    data=json.loads(file.read_text())
    data[0]["version_id"]="wrong"
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError,match="version"):
        prepare_alternate_reviews(root,{i:[10] for i in range(8)},root/"review")

def test_detects_tampered_cached_document(tmp_path):
    root=_sources(tmp_path)
    prepare_alternate_reviews(root,{i:[10] for i in range(8)},root/"review")
    file=root/"alternate_small_0.json"
    file.write_text(file.read_text().replace("concrete", "invented"))
    with pytest.raises(ValueError,match="cache SHA"):
        verify_alternate_review(root,root/"review")

def test_preview_dev_label_cannot_reuse_old_label(tmp_path):
    root=_sources(tmp_path)
    review=root/"review"
    prepare_alternate_reviews(root,{i:[10] for i in range(8)},review)
    seed=root/"seed.tsv"
    seed.write_text("company_index\tsource_index\tgrade\trationale\n"+
                    "1\t0\t2\tCapability matches the core system procurement domain with limitations.\n")
    profiles={"companies":[{"company_id":"firm-1","name":"Synthetic test"}]}
    output=root/"labels"
    result=persist_preview_dev_labels(root,profiles,seed,review,output,[])
    assert result["new_pairs"]==1 and result["positive_2plus"]==1
    saved=json.loads((output/"alternate_preview_dev_labels.jsonl").read_text().splitlines()[0])
    assert saved["split"]=="targeted_development"
    assert saved["human_approved"] is False and saved["full_task_approved"] is False
    with pytest.raises(ValueError,match="previously used"):
        persist_preview_dev_labels(root,profiles,seed,review,root/"other_labels",
                                   [{"company_id":"firm-1","notice_version_id":"v0"}])

def test_no_complete_task_promotion(tmp_path):
    root=_sources(tmp_path)
    prepare_alternate_reviews(root,{i:[10] for i in range(8)},root/"review")
    path=root/"review"/"alternate_review_candidates.jsonl"
    records=[json.loads(x) for x in path.read_text().splitlines()]
    records[0]["full_task_verified"]=True
    path.write_text("".join(json.dumps(x)+"\n" for x in records))
    with pytest.raises(ValueError,match="manifest SHA"):
        verify_alternate_review(root,root/"review")


def test_generalized_twelve_source_batches_and_scope_gate(tmp_path):
    root=_sources(tmp_path)
    targets=json.loads((root/"alternate_targets_8.json").read_text())
    for k in range(8,12):
        targets.append({"index":k,"version_id":f"v{k}","document_id":f"d{k}",
                        "name":f"work_scope{k}","file_sha256":"a"*64,
                        "extracted_text_sha256":"b"*64})
    (root/"alternate_targets_12.json").write_text(json.dumps(targets),encoding="utf-8")
    for start in (8,10):
        docs=[{"id":f"d{k}","version_id":f"v{k}","name":f"work_scope{k}",
               "file_sha256":"a"*64,"extracted_text_sha256":"b"*64,
               "sample":[{"block_index":10,
                          "text":"This construction scope is detailed sufficiently for development review "+str(k),
                          "full_char_count":80}]}
              for k in (start,start+1)]
        (root/f"alternate_small_{start}.json").write_text(json.dumps(docs),encoding="utf-8")
    status={i:("DIRECT_TASK_EXCERPT" if i%2==0 else "PARTIAL_TASK_EXCERPT") for i in range(12)}
    output=root/"generalized"
    manifest=prepare_alternate_reviews(root,{i:[10] for i in range(12)},output,
               targets_file="alternate_targets_12.json",
               sample_files=tuple(f"alternate_small_{i}.json" for i in range(0,12,2)),
               scope_status=status,preview_char_limit=700)
    assert manifest["alternate_attachment_count"]==12
    assert manifest["recovered_task_excerpt_candidates"]==6
    assert verify_alternate_review(root,output)["verified_previews"]==12


def test_incomplete_or_partial_review_cannot_generate_new_labels(tmp_path):
    root=_sources(tmp_path)
    review=root/"partial"
    prepare_alternate_reviews(root,{0:[10]},review,
        scope_status={0:"PARTIAL_TASK_EXCERPT"})
    seed=root/"partial_seed.tsv"
    seed.write_text("company_index\tsource_index\tgrade\trationale\n"+
                    "1\t0\t2\tThis preview is incomplete and cannot support a full business relevance label.\n")
    profiles={"companies":[{"company_id":"firm-1","name":"Synthetic company"}]}
    with pytest.raises(ValueError,match="incomplete or partial"):
        persist_preview_dev_labels(root,profiles,seed,review,root/"partial_labels",[])


def test_selected_full_blocks_sha_and_version_comparison(tmp_path):
    from app.ml_recommendations.alternate_source_review import verify_complete_selected_blocks
    root=_sources(tmp_path)
    review=root/"full_review"
    prepare_alternate_reviews(root,{i:[10] for i in range(8)},review)
    rows=[]
    for start in (0,2,4,6):
        for sample in json.loads((root/f"alternate_small_{start}.json").read_text()):
            rows.append({"document_id":sample["id"],"version_id":sample["version_id"],
                         "file_sha256":sample["file_sha256"],
                         "extracted_text_sha256":sample["extracted_text_sha256"],
                         "blocks":sample["sample"]})
    (root/"full_0.json").write_text(json.dumps(rows))
    result=verify_complete_selected_blocks(root,review,("full_0.json",))
    assert result["verified_document_count"]==8 and result["human_approved"] is False
    rows[0]["blocks"][0]["text"]="Different evidence"
    (root/"full_0.json").write_text(json.dumps(rows))
    with pytest.raises(ValueError,match="differs from preview"):
        verify_complete_selected_blocks(root,review,("full_0.json",))


def test_selected_full_blocks_partial_export_fails(tmp_path):
    from app.ml_recommendations.alternate_source_review import verify_complete_selected_blocks
    root=_sources(tmp_path)
    review=root/"full_review"
    prepare_alternate_reviews(root,{i:[10] for i in range(8)},review)
    sample=json.loads((root/"alternate_small_0.json").read_text())[0]
    full={"document_id":sample["id"],"version_id":sample["version_id"],
          "file_sha256":sample["file_sha256"],
          "extracted_text_sha256":sample["extracted_text_sha256"],
          "blocks":sample["sample"]}
    (root/"full_0.json").write_text(json.dumps([full]))
    with pytest.raises(ValueError,match="Not all selected"):
        verify_complete_selected_blocks(root,review,("full_0.json",))


def test_source_family_overlap_flags_duplicate_versions_and_same_extracted_text():
    from app.ml_recommendations.alternate_source_review import audit_alternate_family_overlap
    q=[
       {"notice_id":"A","notice_version_id":"v1"},
       {"notice_id":"A","notice_version_id":"v2"},
       {"notice_id":"B","notice_version_id":"v3"},
       {"notice_id":"C","notice_version_id":"v4"}
    ]
    reviews=[
       {"reviewed_candidate_index":0,"notice_version_id":"v1","extracted_text_sha256_rds":"x1"},
       {"reviewed_candidate_index":1,"notice_version_id":"v2","extracted_text_sha256_rds":"x2"},
       {"reviewed_candidate_index":2,"notice_version_id":"v3","extracted_text_sha256_rds":"same"},
       {"reviewed_candidate_index":3,"notice_version_id":"v4","extracted_text_sha256_rds":"same"}
    ]
    relation={"edges":[{"notice_id":"A","previous_notice_id":"OUTSIDE","match_confidence":"CONFIRMED"}],
              "visited_ids":["A","B","C","OUTSIDE"]}
    r=audit_alternate_family_overlap(q,reviews,relation)
    assert r["same_notice_multiple_version_groups"]==[[0,1]]
    assert r["same_extracted_text_digest_groups"]==[[2,3]]
    assert r["seed_notices_connected_to_outside_sample"]==1
    assert r["independent_time_family_split_ready"] is False
