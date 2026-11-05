"""Authored role and review-context bindings for a fixed candidate set."""
from semantic_review import _fact_span

def instances(p):
 pid=p['project_id'];actor=p['pov_character']
 if pid=='review-old-lord-monitor':
  q='五名来人进入研究所的真实目的';clue='监控画面中五人的行动';topic='研究所内的这次事件';mask=p['characters'][1]
  anchors=['f002','f001','f003','f004','f004','f004','f003','f003','f004']
 elif pid=='review-organs-forensic-inference':
  q='这次案件是否模仿既往案件';clue='自己进行的尸体检查';topic='这次被称为模仿犯案的事件';mask=actor
  anchors=['f003','f002','f002','f006','f006','f006','f005','f005','f006']
 elif pid=='public-obstructed-inquiry':
  q='渡口失踪案中失踪者的去向';clue='案发夜的小船记录';topic='渡口失踪案';mask=actor
  anchors=['f001','f002','f003','f001','f001','f001','f001','f001','f001']
 elif pid=='public-confirmed-answer':
  q='库房起火的原因';clue='完整监控记录';topic='库房火灾';mask=actor
  anchors=['f002','f001','f001','f003','f003','f003','f003','f002','f003']
 else:raise ValueError('Unknown fixed pilot project')
 facts={f['id']:f for f in p['facts']};scenes={s['id']:s for s in p['scenes']}
 def anchor(fid):
  f=facts[fid];start,end=_fact_span(f,scenes[f['scene_id']]['text'])
  return dict(scene_id=f['scene_id'],start=start,end=end)
 specs=[('truth_pursuit',dict(actor=actor,question=q),['investigating','obstructed']),
        ('identity_mask',dict(actor=mask),['concealed_identity']),
        ('homeopathic_magic',dict(topic=topic),['surrogate','belief']),
        ('suspense_inquiry',dict(actor=actor,question=q,clue=clue),['unresolved','available_clue']),
        ('revelation',dict(actor=actor,question=q),['setup','confirmed'])]
 cursor=0;out=[]
 for mid,bindings,conditions in specs:
  mapping={c:anchor(fid) for c,fid in zip(conditions,anchors[cursor:cursor+len(conditions)])};cursor+=len(conditions)
  if mid=='suspense_inquiry' and pid=='review-organs-forensic-inference':
   mapping['tentative_statement']=anchor('f006')
  out.append(dict(id=mid,motif_id=mid,bindings=bindings,anchors=mapping))
 return out
