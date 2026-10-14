import json,re,collections,time
from pathlib import Path
from bidengine.document.chunking import chunk_source_blocks
from bidengine.pipeline.evaluation_role_guard import _is_scoring_only_chunk
root=Path('eval/golden')
inputs=sorted(root.rglob("*.blocks.json"))
signal=re.compile(r'실\s*적|수행\s*실적|사업\s*실적',re.I)
score=re.compile(r'(정량\s*평가|정량적\s*평가|평가\s*항목|수행실적\s*평가|실적\s*평가|평\s*점|점\s*수|배\s*점|평가\s*등급)',re.I)
eligibility=re.compile(r'(입찰\s*참가\s*자격|참가\s*자격\s*및\s*조건|입찰\s*참가\s*조건|자격\s*요건)',re.I)
amount=re.compile(r'(\d+[천만억]?\s*원|[\d,]+\s*(?:만원|천만원)|\d+\s*건)',re.I)
heads=collections.Counter()
by_family=collections.Counter()
summary=collections.Counter()
examples=[]
matched_examples=[]
bad=[]
t=time.monotonic()
for i,p in enumerate(inputs):
 try:
  blocks=json.loads(p.read_text(encoding='utf-8-sig'))
  chunks=chunk_source_blocks(blocks,max_chars=1800)
 except Exception as e:
  bad.append((str(p),str(e)[:100]));continue
 summary['files']+=1
 summary['chunks']+=len(chunks)
 by_family[p.relative_to(root).parts[0]]+=1
 for chunk in chunks:
  txt=chunk.get('text') or ''
  if _is_scoring_only_chunk(txt):
   summary['guard_accepted_chunks']+=1
   if signal.search(txt):
    summary['guard_accepted_performance_chunks']+=1
    if len(matched_examples)<130:matched_examples.append({'file':str(p.relative_to(root)),'chunk':chunk.get('chunk_id'),'head':txt[:260]})
  if signal.search(txt):
   summary['performance_chunks']+=1
   if score.search(txt):
    summary['performance_score_chunks']+=1
    m=score.search(txt)
    style=re.sub(r'\s+',' ',txt[:85])
    heads[style[:72]]+=1
    if not eligibility.search(txt):
     summary['score_only_no_eligibility_text']+=1
    if not amount.search(txt):
     continue
    if len(examples)<120:
     examples.append({'file':str(p.relative_to(root)),'chunk':str(chunk.get('chunk_id')),'head':txt[:250],'full_len':len(txt)})
   if eligibility.search(txt):summary['performance_eligibility_chunks']+=1
   if score.search(txt) and eligibility.search(txt):summary['mixed_chunks']+=1
print('CORPUS',json.dumps(dict(summary),ensure_ascii=True))
print('FAMILIES',json.dumps(by_family,ensure_ascii=True))
print('ERRORS',len(bad),'SECONDS',round(time.monotonic()-t,2))
for a in examples[:12]:print('EXAMPLE',json.dumps(a,ensure_ascii=True))
for a in matched_examples[:55]:print('ACCEPT',json.dumps(a,ensure_ascii=True))