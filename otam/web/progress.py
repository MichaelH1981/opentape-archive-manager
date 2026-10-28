"""Read-only phase progress; never confuse transferred bytes with VERIFIED."""
import json


def job_progress(db, ident, plan, state):
    medium_index=1;medium_count=1
    if state in ('RUNNING','PLANNING'):
        linked=db.execute("SELECT details_json FROM events WHERE job_id=? AND event='planning_child' ORDER BY seq DESC LIMIT 1",(ident,)).fetchone()
        if linked:
            ident=json.loads(linked['details_json'])['child_job']
    if isinstance(plan,dict) and plan.get('children'):
        children=plan['children'];medium_count=len(children)
        for medium_index,child in enumerate(children,1):
            r=db.execute('SELECT state FROM jobs WHERE id=?',(child['job_id'],)).fetchone()
            if not r or r['state']!='VERIFIED':break
        ident=child['job_id']
    rows=list(db.execute('SELECT archive_id,phase,state,progress_bytes,total_bytes,updated FROM staged_archives WHERE job_id=? ORDER BY updated DESC',(ident,)))
    if not rows:
        if state not in ('RUNNING','PLANNING'):return None
        event=db.execute("SELECT time,details_json FROM events WHERE job_id=? AND event='planning_progress' ORDER BY seq DESC LIMIT 1",(ident,)).fetchone()
        if not event:return None
        d=json.loads(event['details_json']);total=d.get('total_bytes');done=d.get('bytes',0)
        return {**d,'percent': min(100,100*done/total) if total and d['phase'] in ('HASHING','STAGING') else None,
                'total_bytes':total,'updated':event['time'],'job_state':state,'planning':True,
                'bytes_per_second':done/max(d.get('elapsed_seconds',0),1e-9)}
    row=next((r for r in rows if r['state']=='RUNNING'),rows[0])
    total=row['total_bytes'];done=row['progress_bytes']
    phase=row['phase']
    percent=None if phase=='INVENTORY' or total<=0 else max(0,min(100,100*done/total))
    verified=db.execute("SELECT count(*) FROM archives WHERE job_id=? AND state='VERIFIED'",(ident,)).fetchone()[0]
    event_name='staging_progress' if phase=='STAGING' else 'validation_progress' if phase=='VALIDATION' else 'io_progress' if phase in ('TAPE_WRITE','TAPE_READBACK') else None
    event=db.execute("SELECT time,details_json FROM events WHERE job_id=? AND event=? AND json_extract(details_json,'$.archive')=? ORDER BY seq DESC LIMIT 1",(ident,event_name,row['archive_id'])).fetchone() if event_name else None
    extra=json.loads(event['details_json']) if event else {}
    io = (dict(extra, sample_time=event['time']) if event and event_name == 'io_progress'
          and extra.get('phase') == phase else None)
    return {**{k:extra[k] for k in ('path','files','total_files','bytes_per_second') if k in extra}, 'phase':phase,'percent':percent,'bytes':done,'total_bytes':total,
            'updated':row['updated'],'archives_verified':verified,'archives_total':len(rows),
            'medium_index':medium_index,'medium_count':medium_count,'job_state':state,'io':io}
