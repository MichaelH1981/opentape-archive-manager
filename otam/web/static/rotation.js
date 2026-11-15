import { $, $$, esc, bytes, date, short, badge } from './common.js';
import { state } from './state.js';
import { api, enqueue } from './api.js';
import { modal, closeModal, heading, note, toast } from './ui.js';

let current = [];
export async function rotationPage() {
  const result = await api('/rotation'); current = result.items;
  const admin = state.account?.role === 'admin';
  const operator = state.account?.role !== 'viewer';
  const used = new Set(current.flatMap(p=>p.sets.flatMap(s=>s.members.map(m=>m.id))));
  const choices = state.media.filter(m=>m.class === 'rotation' && !used.has(m.id) && ['READY','IN_USE'].includes(m.state));
  const options = choices.map(m=>`<option value="${esc(m.id)}">${esc(m.label)} · ${bytes(m.capacity)}</option>`).join('');
  return heading('Rollierende Sicherungen.', 'Unabhängige Vollgenerationen auf erweiterbaren Bandsätzen.',
    admin ? '<button class="button primary" id="rotation-new">Sicherungsregel anlegen</button>' : '') +
    note('Vorbereitung benötigt einen konsistenten, unveränderlichen Quellenstand. Für Borg vorher eine gesperrte Kopie oder einen geeigneten Snapshot bereitstellen. OTAM erstellt hier keinen automatischen Borg-Snapshot.', 'info') +
    (!result.physical_recycling_enabled && state.node.operation_mode === 'physical' ? note('Physische Wiederverwendung ist bis zur gesonderten Hardwareabnahme gesperrt. Neue freie Rotationsmedien können für Vollsicherungen verwendet werden.', 'warning') : '') +
    current.map(p=>`<section class="panel" style="margin-top:20px"><div class="panel-header"><div><h2>${esc(p.name)}</h2><p>${p.options.set_count} Bandsätze · ${p.options.keep_during_update} Bandstände während Erneuerung erhalten · ${p.options.retain_days} Tage Mindestaufbewahrung</p></div>${admin?`<button class="button" data-rotation-edit="${esc(p.id)}">Regel bearbeiten / Sätze ergänzen</button>`:''}</div>
    ${p.options.keep_during_update===0 ? `<div class="panel-body">${note('Beim Wiederverwenden kann zeitweise kein vollständiger Bandstand verbleiben. Die vollständige lokale Quellenaufnahme bleibt bis zum erfolgreichen Abschluss erhalten.', 'warning')}</div>`:''}
    <div class="panel-body">${p.sets.map(s=>`<article style="margin-bottom:24px"><h3>${esc(s.name)} · ${bytes(s.capacity)}</h3><p>${s.members.map(m=>`${esc(m.label)} · ${esc(m.serial || short(m.id))} · ${esc(m.state)}`).join('<br>') || 'Noch keine Kassetten zugeordnet.'}</p>
    ${admin ? `<form class="rotation-member" data-set="${esc(s.id)}"><label>Weitere registrierte Rotationskassette<select name="media_id" required><option value="">Kassette auswählen</option>${options}</select></label><button class="button" ${!options?'disabled':''}>Kassette hinzufügen</button></form>`:''}
    ${operator?`<button class="button primary" data-rotation-plan="${esc(p.id)}" data-set="${esc(s.id)}">Neue Vollsicherung auf diesem Satz vorbereiten</button>`:''}</article>`).join('')}
    <h3>Sicherungsgenerationen</h3>${p.generations.map(g=>`<article style="border-top:1px solid var(--border);padding:16px 0"><strong>${esc(short(g.id))}</strong> · ${date(g.created)} · ${badge(g.state)}
    <p>${esc(g.data.reason || g.data.error || '')} ${g.data.required_bytes ? `· Bedarf ${bytes(g.data.required_bytes)} / Satz ${bytes(g.data.available_bytes)}`:''}</p>
    ${operator && !g.archive_job && ['WAITING_CAPACITY','WAITING_APPROVAL','WAITING_MEDIA'].includes(g.state)?`<button class="button" data-rotation-bind="${esc(g.id)}">Kapazität prüfen / Schreibplan erstellen</button>`:''}
    ${admin && result.physical_recycling_enabled || admin && state.node.operation_mode==='simulator' ? (g.data.recycle_media || []).filter(()=>!g.archive_job && g.state==='WAITING_APPROVAL').map(m=>`<button class="button" data-rotation-recycle="${esc(g.id)}" data-medium="${esc(m)}">Wiederverwendung ${esc(short(m))} prüfen</button>`).join(''):''}
    ${g.archive_job ? `<button class="button" data-job="${esc(g.archive_job)}">Archivplan / Bandwechsel</button>`:''}
    ${operator && g.state==='VERIFIED'?`<button class="button" data-rotation-restore="${esc(g.id)}">Gesamten Stand wiederherstellen</button>`:''}
    ${operator && g.state==='VERIFIED' && g.data.source_capture_retained?`<button class="button" data-rotation-clean="${esc(g.id)}">Lokale Quellenaufnahme bereinigen</button>`:''}
    ${admin && !g.archive_job && ['WAITING_CAPACITY','WAITING_APPROVAL','WAITING_MEDIA'].includes(g.state)?`<button class="button" data-rotation-cancel="${esc(g.id)}">Vorbereitung abbrechen (Daten erhalten)</button>`:''}
    ${admin?`<button class="button" data-rotation-protect="${esc(g.id)}" data-value="${!g.data.protected}">${g.data.protected?'Schutz aufheben':'Dauerhaft schützen'}</button>`:''}
    </article>`).join('') || '<p>Noch keine Sicherungsgeneration vorhanden.</p>'}</div></section>`).join('') +
    (result.restores || []).map(r=>`<section class="panel"><div class="panel-body"><h3>Satz-Restore ${esc(short(r.id))} · ${badge(r.state)}</h3><p>${esc(r.error || r.next_media_id || '')}</p>${operator && r.state==='WAITING_MEDIA'?`<button class="button" data-rotation-restore-step="${esc(r.id)}">Nächstes Restoremedium lesen</button>`:''}</div></section>`).join('');
}

export function bindRotation(refresh) {
  function handle(el, action) { el?.addEventListener('click', async()=>{try { await action(el); await refresh(); } catch(e) {toast(e.message,'error');}}); }
  const edit = (policy=null)=>{
    const o=policy?.options || {set_count:1,keep_during_update:0,retain_days:0,target:75000000000,excluded_paths:[]};
    modal(policy?'Sicherungsregel bearbeiten':'Neue rollierende Vollsicherung', `<form id="rotation-policy-form"><div class="form-grid">
    <label>Name<input name="name" maxlength="100" value="${esc(policy?.name || '')}" required></label>
    <label>Quelle<select name="source_id">${state.node.sources.map(s=>`<option value="${esc(s.id)}" ${s.id===o.source_id?'selected':''}>${esc(s.label)}</option>`).join('')}</select></label>
    <label>Staging<select name="staging_id">${(state.node.staging_locations || []).map(s=>`<option value="${esc(s.id)}" ${s.id===o.staging_id?'selected':''}>${esc(s.label)}</option>`).join('')}</select></label>
    <label>Gewünschte Bandsätze<input name="set_count" type="number" min="${policy?.sets.length || 1}" max="32" value="${o.set_count}" required></label>
    <label>Während Erneuerung erhaltene Bandstände<input name="keep_during_update" type="number" min="0" max="31" value="${o.keep_during_update}" required></label>
    <label>Mindestaufbewahrung in Tagen<input name="retain_days" type="number" min="0" max="36500" value="${o.retain_days}" required></label>
    <label>TAR-Zielgröße in GB<input name="target" type="number" min="0.001" step="0.001" value="${o.target/1e9}" required></label>
    <label>Ausschlüsse (ein relativer Pfad je Zeile)<textarea name="excluded_paths">${esc(o.excluded_paths.join('\n'))}</textarea></label></div>
    <p>Null erhaltene Bandstände erlaubt Ein-Satz-Betrieb mit vollständiger lokaler Quellenaufnahme. Externe Kopien werden von OTAM nicht automatisch geprüft. Dauerarchive bleiben ausgeschlossen.</p>
    <button class="button primary">Regel speichern</button></form>`);
    $('#rotation-policy-form').addEventListener('submit', async e=>{e.preventDefault(); const d=new FormData(e.target); const body=Object.fromEntries(d);
      for(const k of ['set_count','keep_during_update','retain_days']) body[k]=Number(body[k]); body.target=Math.round(Number(body.target)*1e9);body.excluded_paths=body.excluded_paths.split('\n').map(x=>x.trim()).filter(Boolean);
      try {await api('/rotation/policies'+(policy?'/'+policy.id:''),{method:policy?'PUT':'POST',body:JSON.stringify(body)});closeModal();await refresh();}catch(err){toast(err.message,'error');}
    });
  };
  handle($('#rotation-new'),()=>edit());
  $$('[data-rotation-edit]').forEach(el=>handle(el,()=>edit(current.find(p=>p.id===el.dataset.rotationEdit))));
  $$('.rotation-member').forEach(form=>form.addEventListener('submit',async e=>{e.preventDefault();try{await api('/rotation/sets/'+form.dataset.set+'/members',{method:'POST',body:JSON.stringify({media_id:new FormData(form).get('media_id')})});await refresh();}catch(err){toast(err.message,'error');}}));
  $$('[data-rotation-plan]').forEach(el=>handle(el,async()=>{
    if (!confirm('Ist die Quelle ein vollständiger, konsistenter und während der lokalen Übernahme unveränderlicher Stand? Bei Borg dürfen insbesondere create/prune/compact diesen Stand nicht verändern.')) return;
    await enqueue('plan-rotation',{policy_id:el.dataset.rotationPlan,set_id:el.dataset.set,consistent_source:true});
  }));
  $$('[data-rotation-clean]').forEach(el=>handle(el,async()=>{if(confirm('Vollständig geprüfte lokale Quellenaufnahme jetzt entfernen?'))await enqueue('cleanup-rotation',{generation_id:el.dataset.rotationClean});}));
  $$('[data-rotation-cancel]').forEach(el=>handle(el,async()=>{if(confirm('Vorbereitung abbrechen und Dateien erhalten?'))await api('/rotation/generations/'+el.dataset.rotationCancel+'/cancel',{method:'POST',body:JSON.stringify({confirm:el.dataset.rotationCancel})});}));
  $$('[data-rotation-bind]').forEach(el=>handle(el,()=>enqueue('bind-rotation',{generation_id:el.dataset.rotationBind})));
  $$('[data-rotation-protect]').forEach(el=>handle(el,()=>api('/rotation/generations/'+el.dataset.rotationProtect+'/protection',{method:'PUT',body:JSON.stringify({protected:el.dataset.value==='true'})})));
  $$('[data-rotation-recycle]').forEach(el=>handle(el,async()=>{
    const g=await api('/rotation/recycle/prepare',{method:'POST',body:JSON.stringify({generation_id:el.dataset.rotationRecycle,media_id:el.dataset.medium})});
    const phrase=prompt(`Alle Inhalte dieser Kassette werden unbrauchbar. Betroffene Generationen: ${g.affected.join(', ') || 'keine'}. Bestätigung exakt eingeben:\n${g.confirmation}`);
    if(phrase!==g.confirmation)return;
    await enqueue('recycle-rotation',{approval_id:g.id,confirmation:phrase,destructive_confirmed:true});
  }));
  $$('[data-rotation-restore]').forEach(el=>handle(el,async()=>{const name=prompt('Neuer Zielordner für den vollständigen Restore:');if(name)await enqueue('restore-rotation',{generation_id:el.dataset.rotationRestore,target_name:name});}));
  $$('[data-rotation-restore-step]').forEach(el=>handle(el,()=>enqueue('restore-rotation',{restore_job:el.dataset.rotationRestoreStep})));
}
