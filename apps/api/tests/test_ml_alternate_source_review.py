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
