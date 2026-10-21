"""Read-only phase progress; never confuse transferred bytes with VERIFIED."""
import json


def job_progress(db, ident, plan, state):
    medium_index=1;medium_count=1
    if isinstance(plan,dict) and plan.get('children'):
        children=plan['children'];medium_count=len(children)
        for medium_index,child in enumerate(children,1):
            r=db.execute('SELECT state FROM jobs WHERE id=?',(child['job_id'],)).fetchone()
            if not r or r['state']!='VERIFIED':break
        ident=child['job_id']
    rows=list(db.execute('SELECT phase,state,progress_bytes,total_bytes,updated FROM staged_archives WHERE job_id=? ORDER BY updated DESC',(ident,)))
    if not rows:return None
    row=next((r for r in rows if r['state']=='RUNNING'),rows[0])
    total=row['total_bytes'];done=row['progress_bytes']
    phase=row['phase']
    percent=None if phase=='INVENTORY' or total<=0 else max(0,min(100,100*done/total))
    verified=db.execute("SELECT count(*) FROM archives WHERE job_id=? AND state='VERIFIED'",(ident,)).fetchone()[0]
    return {'phase':phase,'percent':percent,'bytes':done,'total_bytes':total,
            'updated':row['updated'],'archives_verified':verified,'archives_total':len(rows),
            'medium_index':medium_index,'medium_count':medium_count,'job_state':state}
