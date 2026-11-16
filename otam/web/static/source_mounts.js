import {$,$$,esc} from './common.js';
import {api} from './api.js';
import {localize} from './i18n.js';
import {modal,note,toast} from './ui.js';
export async function sourceMountDialog(useSource) {
  const r=await api('/source-mounts');
  modal('Quellen einbinden', `${note(r.message,'info')}${!r.enabled?note('Der administrative Mountdienst ist noch nicht aktiviert.','warning'):''}
  <form id="source-mount-form"><label>Typ<select name="kind"><option value="nfs">NFS</option><option value="smb">SMB</option><option value="usb">USB</option></select></label><div id="mount-fields"></div><p>Nur lesend, ohne Ausführungsrechte. Es werden keine Datenträger formatiert oder vorhandene Mounts ersetzt. NAS-Dateirechte müssen den Zugriff erlauben.</p><button class="button primary" ${r.enabled?'':'disabled'}>Quelle lesend einbinden</button></form>
  <h3>Mountstatus</h3><button class="button" id="refresh-source-mounts">Status aktualisieren</button><div id="mount-status"></div>`);
  const form=$('#source-mount-form');
  const fields=()=>{
    const k=form.elements.kind.value;
    const secure=location.protocol==='https:' || ['localhost','127.0.0.1','[::1]'].includes(location.hostname);
    $('button',form).disabled=!r.enabled || (k==='smb' && !secure);
    $('#mount-fields').innerHTML=k==='usb'?`<label>Unbenutztes USB-Dateisystem<select name="uuid" required><option value="">USB-Dateisystem auswählen</option>${r.usb.map(d=>`<option value="${esc(d.uuid)}">${esc(d.path)} · ${esc(d.fstype)} · ${esc(d.uuid)}</option>`).join('')}</select></label><p>USB: ext4, XFS, Btrfs, FAT und exFAT. System- und Stagingdatenträger bleiben ausgeschlossen.</p>${!r.usb.length?note('Kein unbenutztes unterstütztes USB-Dateisystem erkannt. Bereits eingebundene Datenträger werden nicht erneut gemountet.','warning'):''}`:
      `<label>NAS-IPv4-Adresse<input name="server" required placeholder="192.168.1.120" autocomplete="off"></label>`+
      (k==='nfs'?`<label>NFS-Export<input name="export" required placeholder="/backup"></label><p>NFS verwendet numerische Benutzer-/Gruppenrechte. Lesend mounten umgeht keine fehlenden NAS-Leserechte.</p>`:
      `<label>SMB-Freigabe<input name="share" required placeholder="backup"></label><label>Benutzer<input name="username" required autocomplete="off"></label><label>Passwort<input name="password" type="password" autocomplete="off"></label><label>Domäne (optional)<input name="domain" autocomplete="off"></label><label>SMB-Version<select name="version"><option value="3.1.1">3.1.1</option><option value="3.0">3.0</option><option value="2.1">2.1</option><option value="2.0">2.0 (älteres NAS)</option></select></label><p>Das Passwort wird nur für diesen Mount verwendet und nicht dauerhaft gespeichert. Nach einem Neustart ist erneutes Einbinden erforderlich.</p>`);
    if(k==='smb') {
      const box=$('#mount-fields');
      box.insertAdjacentHTML('afterbegin',note('Bei älteren NAS kann eine ausdrücklich gewählte SMB-Version nötig sein. Kein automatischer Rückfall auf SMB1.','info'));
      if(!secure) {
        const fieldset=document.createElement('fieldset');fieldset.disabled=true;
        while(box.firstChild)fieldset.append(box.firstChild);
        box.append(fieldset);
        const info=document.createElement('div');
        info.innerHTML=note('Die Felder sind über unverschlüsseltes LAN-HTTP gesperrt. Öffne den geschützten lokalen SSH-Zugang oder HTTPS und wähle dort erneut SMB.','warning')+'<a class="button" href="http://127.0.0.1:8766/#planning" rel="noreferrer">Lokalen SSH-Zugang öffnen (Port 8766)</a><p>Der lokale Zugang benötigt einen eingerichteten SSH-Tunnel auf diesem Computer.</p>';
        box.prepend(info);
      }
    }
    localize($('#mount-fields'));
  };
  form.elements.kind.addEventListener('change',fields);fields();
  let submitting=false;
  const updateSubmit=()=>{$('button',form).disabled=submitting || !r.enabled || (form.elements.kind.value==='smb' && !(location.protocol==='https:' || ['localhost','127.0.0.1','[::1]'].includes(location.hostname)));};
  let pending=null;
  async function status(){
    const data=await api('/source-mounts?usb=false');
    const box=$('#mount-status');if(!box)return;
    box.innerHTML=(pending&&!data.items.some(x=>x.id===pending)?note('Mountanfrage wartet auf den geschützten Hilfsdienst.','info'):'')+data.items.slice().reverse().map(m=>`<section class="panel"><div class="panel-body"><strong>${esc(m.kind || 'Mountanfrage')} · ${esc(m.state)}</strong><p class="mono">${esc(m.source || '')}</p><p class="mono">${esc(m.target || '')}</p>${m.error?note(m.error,'warning'):''}${m.state==='MOUNTED'?`<button class="button" data-mount-use="${esc(m.target)}">Als Quelle registrieren</button>`:''}</div></section>`).join('');
    localize(box);
    $$('[data-mount-use]',box).forEach(b=>b.addEventListener('click',()=>useSource(b.dataset.mountUse)));
    return data;
  }
  $('#refresh-source-mounts').addEventListener('click',()=>status().catch(e=>toast(e.message,true)));
  form.addEventListener('submit',async e=>{
    e.preventDefault();if(submitting)return;submitting=true;const button=$('button[type=submit]',form)||$('button',form);button.disabled=true;
    const data=Object.fromEntries(new FormData(form));
    try{
      const result=await api('/source-mounts',{method:'POST',body:JSON.stringify(data)});pending=result.id;
      if(form.elements.password)form.elements.password.value='';
      toast('Lesender Mount angefordert. Status wird aktualisiert.');await status();
      const timer=setInterval(async()=>{
        if(!$('#mount-status')){clearInterval(timer);return;}
        try{const d=await status();if(d.items.some(x=>x.id===pending && x.state!=='RUNNING'))clearInterval(timer);}catch(err){clearInterval(timer);toast(err.message,true);}
      },2000);
    }catch(error){toast(error.message,true);}finally{submitting=false;updateSubmit();}
  });
  await status();
}
