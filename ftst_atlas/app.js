'use strict';
(() => {
const $ = id => document.getElementById(id);
if(/\/submit\/?$/.test(window.location.pathname)){initSubmissionPage();return;}
document.querySelector('.shell').hidden=false;
let activeView = 'chat', sending = false, noticeTimer, csrfToken = '';
const conversation = [];
const labels = {chat:'CHAT',knowledge:'WISSEN',tasks:'AUFGABEN',mail:'E-MAILS',bookkeeping:'BUCHHALTUNG',system:'SYSTEM'};
function notify(message,error=false){const node=$('notice');node.textContent=message;node.className='notice'+(error?' error':'');node.hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>{node.hidden=true;},9000);}
async function api(path,options={}){if(options.method&&options.method!=='GET'&&!csrfToken){await loadStatus();if(!csrfToken)throw new Error('Die Sitzung ist noch nicht bereit. Bitte lade den Systemstatus neu.');}const response=await fetch('api/'+path,{...options,headers:{'Content-Type':'application/json',...(csrfToken?{'X-Atlas-CSRF':csrfToken}:{}),...(options.headers||{})},credentials:'same-origin',cache:'no-store'});let payload;try{payload=await response.json();}catch{throw new Error('Die Antwort des Servers konnte nicht gelesen werden. Bitte prüfe den Systemstatus.');}if(!response.ok){if(response.status===403){csrfToken='';throw new Error('Die Sitzungsfreigabe ist abgelaufen oder der Zugriff wurde abgelehnt. Bitte lade die Seite neu und prüfe vor einem erneuten Versuch, ob die Änderung bereits gespeichert wurde.');}throw new Error(payload.error||payload.message||'Die Anfrage konnte nicht abgeschlossen werden.');}return payload;}
function element(tag,className,text){const n=document.createElement(tag);if(className)n.className=className;if(text!==undefined)n.textContent=text;return n;}
function switchView(view){if(!labels[view])return;activeView=view;document.querySelectorAll('.view').forEach(n=>{const selected=n.id==='view-'+view;n.hidden=!selected;n.classList.toggle('active',selected);});document.querySelectorAll('.nav-item').forEach(n=>{const selected=n.dataset.view===view;n.classList.toggle('active',selected);if(selected)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');});$('view-label').textContent=labels[view];if(view==='knowledge'){loadMemories();loadProfile();}if(view==='tasks'){loadTasks();loadJobs();}if(view==='mail')loadMailAccounts();if(view==='bookkeeping'){loadBookkeeping();loadSubmissionAccess();}if(view==='system')loadStatus();}
document.querySelectorAll('[data-view]').forEach(n=>n.addEventListener('click',()=>switchView(n.dataset.view)));
document.querySelector('.brand').addEventListener('click',e=>{e.preventDefault();switchView('chat');});
function addMessage(text,role,error=false){$('chat-intro').hidden=true;const article=element('article','message '+role+(error?' error':''));article.append(element('div','message-author',role==='user'?'Du':error?'Verbindungshinweis':'ATLAS'),element('div','message-text',text));if(role==='assistant'&&!error){const actions=element('div','message-tools');const remember=element('button','tiny-button','Als Wissen übernehmen');remember.type='button';remember.addEventListener('click',()=>{switchView('knowledge');$('memory-text').value=text.slice(0,2000);$('memory-source').value='ATLAS-Entwurf – vom Nutzer zu prüfen';$('memory-text').focus();notify(text.length>2000?'Der Entwurf wurde auf 2.000 Zeichen gekürzt. Bitte prüfe und korrigiere ihn vor dem Speichern.':'Bitte prüfe und korrigiere den Entwurf vor dem Speichern.');});actions.append(remember);article.append(actions);}$('messages').append(article);article.scrollIntoView({behavior:'auto',block:'nearest'});return article;}
$('chat-form').addEventListener('submit',async e=>{e.preventDefault();if(sending)return;const message=$('message').value.trim();if(!message)return;sending=true;addMessage(message,'user');$('message').value='';$('send-button').disabled=true;$('message').disabled=true;$('chat-progress').hidden=false;$('chat-form').setAttribute('aria-busy','true');try{const job=await api('jobs',{method:'POST',body:JSON.stringify({message,mode:$('chat-mode').value,history:conversation.slice(-4).map(entry=>({role:entry.role,content:entry.content.slice(0,500)}))})});const data=await waitJob(job.id);const reply=data.reply||data.response||data.message;if(typeof reply!=='string'||!reply.trim())throw new Error('ATLAS hat keine verwertbare Antwort geliefert.');const article=addMessage(reply,'assistant');renderResult(article,data);conversation.push({role:'user',content:message},{role:'assistant',content:reply});if(conversation.length>4)conversation.splice(0,conversation.length-4);}catch(err){addMessage(err.message+' Ein angenommener Auftrag kann weiterlaufen. Bitte zuerst unter Aufgaben prüfen, bevor du erneut sendest.','assistant',true);}finally{sending=false;$('send-button').disabled=false;$('message').disabled=false;$('chat-progress').hidden=true;$('chat-form').removeAttribute('aria-busy');$('message').focus();}});
$('message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('chat-form').requestSubmit();}});
document.querySelectorAll('[data-prompt]').forEach(n=>n.addEventListener('click',()=>{$('message').value=n.dataset.prompt;$('message').focus();}));
async function loadMemories(){try{const data=await api('memories');const memories=Array.isArray(data)?data:(data.memories||data.items||[]);const list=$('memory-list');list.replaceChildren();$('memory-count').textContent=memories.length+(memories.length===1?' Eintrag':' Einträge');if(!memories.length)list.append(element('p','empty-state','Noch keine Notizen gespeichert. Ergänze deinen ersten Eintrag, damit ATLAS darauf aufbauen kann.'));for(const item of memories){const card=element('article','memory-card');card.append(element('p','memory-text',item.text));const meta=element('div','memory-meta');meta.append(element('span','',item.source||'Eigene Notiz'));const remove=element('button','delete-button','Löschen');remove.type='button';remove.setAttribute('aria-label','Wissenseintrag löschen');remove.addEventListener('click',async()=>{if(!window.confirm('Diesen Wissenseintrag dauerhaft löschen?'))return;remove.disabled=true;try{await api('memories/'+encodeURIComponent(item.id),{method:'DELETE'});await loadMemories();notify('Wissenseintrag gelöscht.');}catch(err){notify(err.message,true);remove.disabled=false;}});meta.append(remove);card.append(meta);list.append(card);}}catch(err){$('memory-list').replaceChildren(element('p','empty-state',err.message));}}
$('memory-form').addEventListener('submit',async e=>{e.preventDefault();const text=$('memory-text').value.trim(),source=$('memory-source').value.trim();if(!text)return;const button=e.currentTarget.querySelector('button[type="submit"]');button.disabled=true;try{await api('memories',{method:'POST',body:JSON.stringify({text,source})});$('memory-text').value='';await loadMemories();notify('Gespeichert. ATLAS kann diese Notiz bei späteren Antworten berücksichtigen.');}catch(err){notify(err.message,true);}finally{button.disabled=false;}});
async function loadTasks(){try{const data=await api('tasks');const tasks=Array.isArray(data)?data:(data.tasks||data.items||[]);const list=$('task-list');list.replaceChildren();const open=tasks.filter(t=>!t.done).length;$('task-count').textContent=String(open);$('tasks-summary').textContent=open+' offen · '+(tasks.length-open)+' erledigt';if(!tasks.length)list.append(element('p','empty-state','Platz für deinen nächsten Schritt. Lege oben deine erste Aufgabe an.'));for(const item of tasks){const row=element('div','task-row'+(item.done?' done':''));const checkbox=element('input');checkbox.type='checkbox';checkbox.checked=!!item.done;checkbox.id='task-'+item.id;const label=element('label','',item.title);label.htmlFor=checkbox.id;checkbox.addEventListener('change',async()=>{checkbox.disabled=true;try{await api('tasks/'+encodeURIComponent(item.id),{method:'PATCH',body:JSON.stringify({done:checkbox.checked})});await loadTasks();}catch(err){checkbox.checked=!checkbox.checked;checkbox.disabled=false;notify(err.message,true);}});const remove=element('button','delete-button','Löschen');remove.type='button';remove.setAttribute('aria-label','Aufgabe löschen');remove.addEventListener('click',async()=>{if(!window.confirm('Diese Aufgabe dauerhaft löschen?'))return;remove.disabled=true;try{await api('tasks/'+encodeURIComponent(item.id),{method:'DELETE'});await loadTasks();notify('Aufgabe gelöscht.');}catch(err){notify(err.message,true);remove.disabled=false;}});row.append(checkbox,label,remove);list.append(row);}}catch(err){$('task-list').replaceChildren(element('p','empty-state',err.message));$('tasks-summary').textContent='Nicht erreichbar';}}
$('task-form').addEventListener('submit',async e=>{e.preventDefault();const title=$('task-title').value.trim();if(!title)return;const button=e.currentTarget.querySelector('button');button.disabled=true;try{await api('tasks',{method:'POST',body:JSON.stringify({title})});$('task-title').value='';await loadTasks();notify('Aufgabe gespeichert.');}catch(err){notify(err.message,true);}finally{button.disabled=false;}});
async function loadStatus(){const short=$('status-short');try{const status=await api('status');csrfToken=status.csrf_token||'';const available=status.ollama_reachable===true||status.ollama?.reachable===true||status.ollama?.available===true;const configuredOnly=(status.ollama_reachable===undefined||status.ollama_reachable===null)&&status.ollama?.reachable===undefined&&status.ollama?.available===undefined;short.classList.toggle('ok',available);short.lastElementChild.textContent=available?'Lokale KI erreichbar':configuredOnly?'ATLAS erreichbar':'KI nicht erreichbar';$('mail-status').textContent=status.mail_enabled?'Bereit zum Abruf.':'E-Mail-Zugriff noch nicht freigegeben. Die Verbindung wird in der ATLAS-Konfiguration eingerichtet.';$('online-status').textContent='OpenAI: '+(status.online?.reason||'nicht eingerichtet')+' · '+(status.online?.used||0)+' / '+(status.online?.limit||10)+' Anfragen heute (UTC).'+(status.online_share_profile?' Firmenprofil wird bei Online-Anfragen mitgegeben.':' Firmenprofil und gespeichertes Wissen werden nicht automatisch übertragen.');const details=$('system-details');details.replaceChildren();const rows=[['ATLAS','Erreichbar'],['HA-Benutzer-ID',status.ha_user_id||'Nicht verfügbar'],['Lokale KI',available?'Erreichbar':configuredOnly?'Bereitschaft noch nicht geprüft':'Nicht erreichbar'],['Modell',status.model||status.ollama?.model||'Nicht gemeldet'],['Version',status.version||'0.1'],['Betrieb','Lokal mit optionaler Online-Beratung'],['Online',status.online?.reason||'Nicht eingerichtet'],['Online-Modell',status.online?.model||'Nicht eingerichtet']];for(const [name,value] of rows)details.append(element('dt','',name),element('dd','',String(value)));if(status.warning)details.append(element('dt','','Hinweis'),element('dd','',String(status.warning)));}catch(err){short.classList.remove('ok');short.lastElementChild.textContent='Nicht erreichbar';$('system-details').replaceChildren(element('dt','','Verbindung'),element('dd','','Nicht erreichbar'));if(activeView==='system')notify(err.message,true);}}
$('refresh-status').addEventListener('click',loadStatus);
loadStatus();loadTasks();
async function loadProfile(){try{const data=await api('profile');$('profile-text').value=data.text||'';}catch(err){notify('Firmenprofil: '+err.message,true);}}
$('profile-form').addEventListener('submit',async e=>{e.preventDefault();const text=$('profile-text').value.trim();const button=e.currentTarget.querySelector('button');button.disabled=true;try{await api('profile',{method:'PUT',body:JSON.stringify({text})});notify('Firmenprofil gespeichert. Neue Antworten verwenden die aktualisierten Angaben.');}catch(err){notify(err.message,true);}finally{button.disabled=false;}});

let mailBusy=false;
$('mail-form').addEventListener('submit',async e=>{
 e.preventDefault();if(mailBusy)return;if(!$('mail-account').value){notify('Bitte wähle zuerst ein freigegebenes Postfach.',true);return;}mailBusy=true;
 const button=e.currentTarget.querySelector('button');button.disabled=true;
 $('mail-list').replaceChildren();$('mail-status').textContent='Postfach wird gelesen …';$('mail-account').disabled=true;
 try{
  const data=await api('mail/preview',{method:'POST',body:JSON.stringify({days:Number($('mail-days').value),account_id:$('mail-account').value})});
  $('mail-status').textContent=data.messages.length+' Nachrichten ab '+data.since+' · '+data.source.mailbox+' · '+data.source.folder+(data.pending?' · Weitere Nachrichten vorhanden, Vorschau unvollständig.':' · Abruf für diesen Zeitraum abgeschlossen.');
  if(!data.messages.length)$('mail-list').append(element('p','empty-state','In diesem Zeitraum wurden keine Nachrichten gefunden.'));
  for(const message of data.messages){
   const card=element('article','card mail-card');
   card.append(element('h2','',message.subject||'(Ohne Betreff)'),element('p','quiet',message.from+' · '+message.date));
   const details=element('details');details.append(element('summary','','Mailtext ansehen'),element('p','message-text',message.body||'(Kein lesbarer Text)'));card.append(details);
   card.append(element('p','field-hint','Quelle: '+message.source.folder+' · UID '+message.uid+' · Postfachgeneration '+message.source.uidvalidity+(message.body_truncated?' · Text gekürzt.':'')+(message.attachments_present?' · Anhänge vorhanden, nicht ausgewertet.':'')));
   if(message.warnings?.length)card.append(element('p','field-hint',message.warnings.join(' ')));
   const actions=element('div','mail-actions'),output=element('div','message-text');output.setAttribute('role','status');
   for(const [action,label] of [['summary','Zusammenfassen'],['draft','Antwortentwurf erstellen']]){
    const b=element('button','secondary',label);b.type='button';
    b.addEventListener('click',async()=>{if(mailBusy)return;mailBusy=true;button.disabled=true;actions.querySelectorAll('button').forEach(n=>n.disabled=true);output.textContent='Lokale KI arbeitet …';
     try{const r=await api('mail/assist',{method:'POST',body:JSON.stringify({id:message.id,action})});output.textContent=(action==='draft'?'ENTWURF – NICHT GESENDET. Bitte vor Verwendung prüfen.\n\n':'ZUSAMMENFASSUNG – bitte prüfen.\n\n')+r.reply+(r.excerpt?'\n\nNur ein gekürzter Textauszug wurde ausgewertet.':'');}
     catch(err){output.textContent=err.message;}finally{mailBusy=false;button.disabled=false;actions.querySelectorAll('button').forEach(n=>n.disabled=false);}});
    actions.append(b);
   }
   card.append(actions,output);$('mail-list').append(card);
  }
 }catch(err){$('mail-status').textContent=err.message;}finally{mailBusy=false;button.disabled=false;$('mail-account').disabled=false;}
});

function renderResult(container,data){
 const textNode=container.querySelector('.message-text')||container;
 if(Array.isArray(data.sources)&&data.sources.length){
  const chars=Array.from(data.reply||'');let cursor=0;const fragment=document.createDocumentFragment();
  const sources=data.sources.slice().sort((a,b)=>a.start_index-b.start_index);
  for(const [i,source] of sources.entries()){
   let url;try{url=new URL(source.url);}catch{continue;}
   if(!['http:','https:'].includes(url.protocol)||url.username||url.password||!Number.isInteger(source.start_index)||!Number.isInteger(source.end_index)||source.start_index<cursor||source.end_index<=source.start_index||source.end_index>chars.length)continue;
   fragment.append(document.createTextNode(chars.slice(cursor,source.start_index).join('')));
   const link=element('a','source-link','['+(i+1)+']');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';link.title=source.title||url.hostname;fragment.append(link);cursor=source.end_index;
  }
  fragment.append(document.createTextNode(chars.slice(cursor).join('')));textNode.replaceChildren(fragment);
 }
 container.append(element('p','field-hint',(data.provider||'Lokal')+' · '+(data.model||'')+(data.online?(data.web_searched?' · Webquellen geprüft':' · Ohne Websuche'):'')+(data.routing_note?' · '+data.routing_note:'')));
}
async function waitJob(id){
 for(let n=0;n<240;n++){
  await new Promise(resolve=>setTimeout(resolve,1500));
  const job=await api('jobs/'+encodeURIComponent(id));
  if(job.status==='completed')return job.result;
  if(job.status==='failed')throw new Error(job.error||'Auftrag fehlgeschlagen.');
 }
 throw new Error('Der Auftrag läuft noch. Das Ergebnis findest du unter Aufgaben. Nicht erneut absenden.');
}
let jobsTimer;
async function loadJobs(){
 clearTimeout(jobsTimer);
 try{const data=await api('jobs');const list=$('job-list');list.replaceChildren();
  for(const job of data.jobs){
   const card=element('article','card mail-card');card.append(element('h3','',job.title||'ATLAS-Auftrag'),element('p','quiet',new Date(job.created_at).toLocaleString('de-DE')+' · '+({queued:'Wartet',running:'In Bearbeitung',completed:'Abgeschlossen',failed:'Fehlgeschlagen'}[job.status]||job.status)));
   if(job.status==='completed'){const detail=element('details');detail.append(element('summary','','Ergebnis ansehen'),element('div','message-text',job.result?.reply||''));renderResult(detail,job.result||{});card.append(detail);}
   if(job.error)card.append(element('p','message-text',job.error));list.append(card);
  }
  if(!data.jobs.length)list.append(element('p','empty-state','Noch keine Hintergrundaufträge.'));
  if(activeView==='tasks'&&data.jobs.some(j=>['queued','running'].includes(j.status)))jobsTimer=setTimeout(loadJobs,3000);
 }catch(err){$('job-list').replaceChildren(element('p','empty-state',err.message));}
}
$('refresh-jobs').addEventListener('click',loadJobs);

// Account IDs remain opaque: only IDs returned by the owner-scoped endpoint are used.
async function loadMailAccounts(){
 if(mailBusy)return;
 const select=$('mail-account');const selected=select.value;
 try{
  const data=await api('mail/accounts');select.replaceChildren();
  for(const account of data.accounts||[]){const option=element('option','',(account.email||account.id)+' · '+(account.folder||'INBOX'));option.value=account.id;select.append(option);}
  if(!select.options.length){select.append(element('option','','Keine freigegebenen Postfächer'));select.options[0].value='';select.disabled=true;$('mail-status').textContent='Kein Postfach freigegeben. Bitte zuerst die Verbindung in der ATLAS-Konfiguration einrichten.';}
  else{select.disabled=false;if(Array.from(select.options).some(o=>o.value===selected))select.value=selected;}
 }catch(err){select.replaceChildren(element('option','','Postfachliste nicht verfügbar'));select.options[0].value='';select.disabled=true;$('mail-status').textContent=err.message;}
}
$('mail-account').addEventListener('change',()=>{$('mail-list').replaceChildren();$('mail-status').textContent='Postfach ausgewählt. Mit „E-Mails abrufen“ eine neue Vorschau laden.';});

let bookkeepingRecords=[], bookkeepingEnabled=false, bookkeepingJob=null, bookkeepingPoll=null, bookkeepingRecordId=null, bookkeepingTotal=0, bookkeepingTruncated=false;
const paymentLabels={unknown:'Unbekannt',unpaid:'Offen',paid:'Bezahlt',partial:'Teilweise bezahlt'};
function localDate(value){if(!value)return 'Nicht gemeldet';const d=new Date(value);return Number.isNaN(d.getTime())?String(value):d.toLocaleString('de-DE');}
function sourceLabel(source={}){
 const provider={mail:'E-Mail',billomat:'Billomat',upload:'Upload',employee:'Mitarbeiter-Upload'}[source.provider]||'Quelle nicht angegeben';
 const parts=[provider];for(const [key,label] of [['account_id','Postfach'],['message_uid','UID'],['attachment_id','Anhang'],['invoice_id','Rechnung'],['reference','Referenz'],['label','Zugang'],['project','Projekt']])if(source[key]!==undefined&&source[key]!==null&&source[key]!=='')parts.push(label+' '+String(source[key]));return parts.join(' · ');
}
function bookkeepingAmount(fields){const amount=fields.gross;if(amount===undefined||amount===null||amount==='')return 'Betrag fehlt';return String(amount)+' '+(fields.currency||'');}
function renderBookkeeping(){
 const list=$('bookkeeping-list');list.replaceChildren();const filter=$('bookkeeping-direction').value;
 const records=bookkeepingRecords.filter(record=>filter==='all'||(filter==='review'?record.reviewed!==true:record.fields?.direction===filter));
 $('bookkeeping-count').textContent=records.length+' angezeigt · '+bookkeepingRecords.filter(record=>record.reviewed!==true).length+' zu prüfen';
 $('bookkeeping-truncated').hidden=!bookkeepingTruncated;$('bookkeeping-truncated').textContent=bookkeepingTruncated?'Nur die neuesten '+bookkeepingRecords.length+' von '+bookkeepingTotal+' Belegen geladen. Der Filter gilt für diese Auswahl; der Monatsexport durchsucht den gesamten Bestand.':'';
 if(!records.length)list.append(element('p','empty-state',bookkeepingEnabled?'Keine passenden Belege vorhanden. Ein Abgleich kann neue Belege übernehmen.':'Die Belegvorbereitung ist noch nicht freigegeben. Bestehende Belege erscheinen nach Einrichtung der Verbindung.'));
 for(const record of records){
  const fields=record.fields||{},card=element('article','card bookkeeping-card'),heading=element('div','bookkeeping-card-heading'),title=element('div');
  title.append(element('span','section-kicker',fields.direction==='outgoing'?'AUSGANGSRECHNUNG':fields.direction==='incoming'?'EINGANGSRECHNUNG':'RICHTUNG UNGEKLÄRT'),element('h3','',fields.supplier||record.filename||'Beleg ohne Rechnungspartner'));
  heading.append(title,element('strong','bookkeeping-amount',bookkeepingAmount(fields)));card.append(heading);
  const badges=element('div','bookkeeping-badges');badges.append(element('span','tag'+(record.reviewed===true?'':' pending'),record.reviewed===true?'Geprüft':'Noch zu prüfen'),element('span','tag neutral','Zahlung: '+(paymentLabels[fields.payment_status]||'Unbekannt')));card.append(badges);
  card.append(element('p','quiet',(fields.invoice_number?'Nr. '+fields.invoice_number:'Rechnungsnummer fehlt')+' · '+(fields.invoice_date||'Datum fehlt')),element('p','field-hint',sourceLabel(record.source)));
  if(record.issues?.length)card.append(element('p','review-warning',record.issues.length+' offene Prüfpunkte'));
  const actions=element('div','mail-actions'),review=element('button','secondary','Beleg prüfen');review.type='button';review.addEventListener('click',()=>openBookkeepingRecord(record.id));actions.append(review);
  if(record.filename){const download=element('a','secondary download-link',record.mime==='application/json'&&!record.documents?.length?'Quelldaten herunterladen':'Belegdatei herunterladen');download.href='api/bookkeeping/'+encodeURIComponent(record.id)+'/document';download.setAttribute('download','');actions.append(download);}
  card.append(actions);list.append(card);
 }
}
function renderSync(sync){
 const node=$('bookkeeping-sync-detail');node.replaceChildren();if(!sync)return;
 if(typeof sync!=='object'){node.append(element('p','field-hint','Abgleichstatus: '+String(sync)));return;}
 const status=sync.status||'';const running=sync.running===true||['queued','running','pending'].includes(status);
 const header=running?'Abgleich ist noch in Bearbeitung.':status==='failed'?'Der letzte Abgleich ist fehlgeschlagen.':sync.pending?'Weitere Belege ausstehend – der Abgleich ist unvollständig.':'Letzter gemeldeter Abgleich';
 const box=element('div','sync-summary');box.append(element('strong','',header));
 const timestamp=sync.last_finished||sync.updated_at||sync.finished_at||sync.completed_at||sync.last_sync||sync.last_run||sync.created_at;
 if(timestamp)box.append(element('p','field-hint',localDate(timestamp)));
 if(sync.error)box.append(element('p','review-warning',String(sync.error)));
 if(Array.isArray(sync.errors))for(const error of sync.errors)box.append(element('p','review-warning',typeof error==='string'?error:((error.source||error.account_id||'Quelle')+': '+(error.message||error.error||'Abruf fehlgeschlagen'))));
 if(sync.message)box.append(element('p','field-hint',String(sync.message)));
 for(const key of ['imported','skipped','duplicates'])if(Number.isFinite(sync[key]))box.append(element('span','tag neutral',({imported:'Übernommen',skipped:'Übersprungen',duplicates:'Bereits vorhanden'}[key])+': '+sync[key]));
 if(sync.auto_sync===true)box.append(element('p','field-hint','Automatischer Abgleich aktiv'+(Number.isFinite(sync.interval_seconds)?' · Intervall '+Math.round(sync.interval_seconds/60)+' Minuten':'')+'.'));
 if(sync.counts){for(const [key,label] of [['mail_messages','E-Mails'],['documents','Belege'],['billomat_invoices','Billomat-Rechnungen'],['pdfs','PDFs']])if(Number.isFinite(sync.counts[key]))box.append(element('span','tag neutral',label+': '+sync.counts[key]));}
 if(sync.pending_pdfs>0)box.append(element('p','review-warning',sync.pending_pdfs+' PDF-Dokumente noch ausstehend.'));
 if(Array.isArray(sync.sources)&&sync.sources.length){const sources=element('details');sources.append(element('summary','','Status je Quelle'));for(const source of sync.sources){const row=element('p','field-hint');row.textContent=String(source.id||source.type||'Quelle')+' · '+(source.error?'Fehler: '+source.error:source.pending?'Noch nicht vollständig abgerufen':'Kein weiterer Abruf gemeldet')+(source.warnings?' · '+source.warnings+' Hinweise':'');sources.append(row);}box.append(sources);}
 if(sync.pending&&!running)box.append(element('p','field-hint','Nicht alle Quellen oder Belege wurden abgeschlossen. Prüfe die Hinweise, bevor du den Export verwendest.'));
 node.append(box);
}
async function loadBookkeeping(){
 try{const data=await api('bookkeeping');bookkeepingRecords=Array.isArray(data.records)?data.records:[];bookkeepingTotal=Number.isInteger(data.total)?data.total:bookkeepingRecords.length;bookkeepingTruncated=data.truncated===true;bookkeepingEnabled=data.enabled===true;$('bookkeeping-status').textContent=bookkeepingEnabled?'Belegvorbereitung freigegeben. Ein Abgleich liest die eingerichteten Quellen.':'Noch nicht freigegeben. Postfächer und Billomat-Zugriff müssen zunächst eingerichtet werden.';$('bookkeeping-sync').disabled=!bookkeepingEnabled||!!bookkeepingJob||data.sync?.running===true;renderBookkeeping();renderSync(data.sync);updateExportLink();}
 catch(err){$('bookkeeping-status').textContent=err.message;$('bookkeeping-sync').disabled=true;$('bookkeeping-list').replaceChildren(element('p','empty-state','Die Belegliste konnte nicht geladen werden. Bitte aktualisieren.'));}
}
async function pollBookkeepingJob(){
 if(!bookkeepingJob)return;
 try{const job=await api('jobs/'+encodeURIComponent(bookkeepingJob));
  if(job.status==='completed'||job.status==='failed'){
   bookkeepingJob=null;clearTimeout(bookkeepingPoll);await loadBookkeeping();
   if(job.status==='failed'){$('bookkeeping-sync-detail').append(element('p','review-warning',job.error||'Der Abgleich ist fehlgeschlagen. Bereits übernommene Belege bleiben erhalten.'));notify('Der Abgleich ist fehlgeschlagen. Bitte die Quellenhinweise prüfen.',true);}
   else notify('Der Abgleichsauftrag ist beendet. Prüfe offene Belege und Quellenhinweise.');
   return;
  }
  $('bookkeeping-status').textContent=job.status==='queued'?'Abgleich wartet auf Ausführung …':'Belege werden abgeglichen. Noch nicht abgeschlossen …';bookkeepingPoll=setTimeout(pollBookkeepingJob,2500);
 }catch(err){bookkeepingJob=null;$('bookkeeping-status').textContent='Auftragsstatus nicht abrufbar. Bitte zuerst unter Aufgaben prüfen, bevor du einen weiteren Abgleich startest.';$('bookkeeping-sync').disabled=true;notify(err.message,true);}
}
$('bookkeeping-sync').addEventListener('click',async()=>{
 if(bookkeepingJob||!bookkeepingEnabled)return;$('bookkeeping-sync').disabled=true;$('bookkeeping-status').textContent='Abgleich wird angefordert …';
 try{const job=await api('bookkeeping/sync',{method:'POST',body:JSON.stringify({})});bookkeepingJob=job.id||job.job_id;if(!bookkeepingJob)throw new Error('Der Auftrag wurde ohne Kennung beantwortet. Bitte zuerst unter Aufgaben nachsehen.');$('bookkeeping-status').textContent='Abgleich angenommen, noch nicht abgeschlossen …';pollBookkeepingJob();}
 catch(err){$('bookkeeping-status').textContent=err.message+' Bitte vor einem erneuten Versuch den Auftragsstatus unter Aufgaben prüfen.';}
});
$('bookkeeping-refresh').addEventListener('click',loadBookkeeping);
$('bookkeeping-direction').addEventListener('change',renderBookkeeping);
const now=new Date();$('bookkeeping-month').value=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0');
function updateExportLink(){const month=$('bookkeeping-month').value,link=$('bookkeeping-export');if(bookkeepingEnabled&&/^\d{4}-(0[1-9]|1[0-2])$/.test(month)){link.href='api/bookkeeping/export?month='+encodeURIComponent(month);link.setAttribute('download','');link.setAttribute('aria-disabled','false');}else{link.removeAttribute('href');link.removeAttribute('download');link.setAttribute('aria-disabled','true');}}
$('bookkeeping-month').addEventListener('change',updateExportLink);
$('bookkeeping-export-form').addEventListener('submit',e=>e.preventDefault());
$('bookkeeping-export').addEventListener('click',e=>{if(e.currentTarget.getAttribute('aria-disabled')==='true')e.preventDefault();});
function showRecordIssues(record){const node=$('bookkeeping-issues');node.replaceChildren();if(record.issues?.length){const box=element('div','review-warning-box');box.append(element('strong','','Vor Freigabe klären'));const list=element('ul');for(const issue of record.issues)list.append(element('li','',String(issue)));box.append(list);node.append(box);}if(record.extraction_notes?.length){const details=element('details');details.append(element('summary','','Hinweise zur Erkennung'));for(const note of record.extraction_notes)details.append(element('p','field-hint',String(note)));node.append(details);}}
async function openBookkeepingRecord(id){
 const dialog=$('bookkeeping-dialog');bookkeepingRecordId=null;$('bookkeeping-review-form').hidden=true;$('bookkeeping-document-meta').replaceChildren(element('p','','Beleg wird geladen …'));$('bookkeeping-issues').replaceChildren();$('bookkeeping-audit-list').replaceChildren();$('bookkeeping-review-message').textContent='';if(!dialog.open)dialog.showModal();
 try{const data=await api('bookkeeping/'+encodeURIComponent(id));const record=data.record||data;bookkeepingRecordId=record.id;const fields=record.fields||{};$('bookkeeping-dialog-title').textContent=record.filename||'Beleg prüfen';const meta=$('bookkeeping-document-meta');meta.replaceChildren(element('p','field-hint',sourceLabel(record.source)));if(record.source?.note)meta.append(element('p','field-hint','Kommentar: '+record.source.note));if(record.sources?.length>1){for(const source of record.sources.slice(1))meta.append(element('p','field-hint',sourceLabel(source)));}
  if(record.sha256)meta.append(element('p','document-hash','Datenstand-Prüfsumme (SHA-256): '+record.sha256));
  if(record.filename){const download=element('a','secondary download-link',record.mime==='application/json'&&!record.documents?.length?'Quelldaten herunterladen':'Belegdatei herunterladen');download.href='api/bookkeeping/'+encodeURIComponent(record.id)+'/document';download.setAttribute('download','');meta.append(download);}
  for(const [key,input] of [['supplier','supplier'],['invoice_number','number'],['invoice_date','date'],['currency','currency'],['net','net'],['tax','tax'],['gross','gross']])$('review-'+input).value=fields[key]??'';
  $('review-payment').value=Object.hasOwn(paymentLabels,fields.payment_status)?fields.payment_status:'unknown';$('review-reviewed').checked=record.reviewed===true;showRecordIssues(record);$('bookkeeping-review-form').hidden=false;
  for(const item of record.audit||[]){const row=element('details');row.append(element('summary','',localDate(item.created_at||item.timestamp)+' · '+({review:'Prüfung gespeichert',ingest:'Beleg übernommen',extract:'Angaben erkannt',attach_original:'Original ergänzt'}[item.action]||'Änderung')));const after=item.after?.fields||item.after||{};for(const [key,label] of [['supplier','Rechnungspartner'],['invoice_number','Rechnungsnummer'],['invoice_date','Datum'],['currency','Währung'],['net','Netto'],['tax','Steuer'],['gross','Brutto'],['payment_status','Zahlungsstatus']])if(after[key]!==undefined)row.append(element('p','field-hint',label+': '+String(after[key])));$('bookkeeping-audit-list').append(row);}
  if(!(record.audit||[]).length)$('bookkeeping-audit-list').append(element('p','field-hint','Noch kein Änderungsverlauf vorhanden.'));
 }catch(err){$('bookkeeping-document-meta').replaceChildren(element('p','review-warning',err.message));}
}
$('bookkeeping-close').addEventListener('click',()=>$('bookkeeping-dialog').close());
function exactDecimal(value){const cleaned=value.trim().replace(',','.');if(!cleaned)return '';if(!/^-?\d{1,12}(\.\d{1,2})?$/.test(cleaned))throw new Error('Beträge bitte mit höchstens zwei Nachkommastellen und ohne Tausendertrennzeichen eingeben.');return cleaned;}
$('bookkeeping-review-form').addEventListener('submit',async e=>{
 e.preventDefault();if(!bookkeepingRecordId)return;const button=e.currentTarget.querySelector('button[type="submit"]');button.disabled=true;$('bookkeeping-review-message').textContent='Prüfung wird gespeichert …';
 try{const fields={supplier:$('review-supplier').value.trim(),invoice_number:$('review-number').value.trim(),invoice_date:$('review-date').value,currency:$('review-currency').value.trim().toUpperCase(),net:exactDecimal($('review-net').value),tax:exactDecimal($('review-tax').value),gross:exactDecimal($('review-gross').value),payment_status:$('review-payment').value,reviewed:$('review-reviewed').checked};const data=await api('bookkeeping/'+encodeURIComponent(bookkeepingRecordId),{method:'PATCH',body:JSON.stringify({fields})});const record=data.record||data;showRecordIssues(record);$('bookkeeping-review-message').textContent=record.reviewed===true?'Angaben gespeichert und als geprüft markiert.':'Angaben gespeichert. Der Beleg bleibt zur Prüfung offen.';await loadBookkeeping();}
 catch(err){$('bookkeeping-review-message').textContent=err.message;}finally{button.disabled=false;}
});

let submissionPublicUrl='';
async function loadSubmissionAccess(){
 try{const data=await api('submissions/access');submissionPublicUrl=data.public_url||'';const list=$('submission-access-list');list.replaceChildren();
  for(const access of data.access||[]){const row=element('div','submission-access-row'),details=element('div');const active=access.active!==false&&!access.revoked;details.append(element('strong','',access.label||'Mitarbeiter-Zugang'),element('p','field-hint',(active?'Aktiv':'Gesperrt')+' · Erstellt '+localDate(access.created_at)+(Number.isInteger(access.submission_count)?' · '+access.submission_count+' Einreichungen':'')));row.append(details);if(active){const revoke=element('button','delete-button','Zugang sperren');revoke.type='button';revoke.addEventListener('click',async()=>{if(!window.confirm('Diesen Uploadzugang sperren? Der bisherige Link funktioniert danach nicht mehr. Bereits eingereichte Belege bleiben erhalten.'))return;revoke.disabled=true;try{await api('submissions/access/'+encodeURIComponent(access.id),{method:'DELETE'});await loadSubmissionAccess();notify('Uploadzugang gesperrt.');}catch(err){notify(err.message,true);revoke.disabled=false;}});row.append(revoke);}list.append(row);}
  if(!(data.access||[]).length)list.append(element('p','empty-state','Noch keine Mitarbeiter-Zugänge angelegt.'));
 }catch(err){$('submission-access-list').replaceChildren(element('p','field-hint',err.message));}
}
function invitationUrl(data){
 try{if(data.url){const url=new URL(data.url);if(url.protocol==='https:'&&!url.username&&!url.password)return url.href;return '';}
  const base=data.public_url||submissionPublicUrl;if(!base)return '';const url=new URL(base);if(url.protocol!=='https:'||url.username||url.password)return '';const invitation=new URL('/submit',url.origin);invitation.hash='token='+encodeURIComponent(data.token);return invitation.href;
 }catch{return '';}
}
$('submission-access-form').addEventListener('submit',async e=>{
 e.preventDefault();const label=$('submission-access-label').value.trim();if(!label)return;const button=e.currentTarget.querySelector('button');button.disabled=true;$('submission-new-access').hidden=true;$('submission-link-value').value='';
 try{const data=await api('submissions/access',{method:'POST',body:JSON.stringify({label})});if(typeof data.token!=='string'||!data.token)throw new Error('Zugang wurde ohne sichtbaren Linkschlüssel beantwortet. Bitte vorhandene Zugänge prüfen, bevor du erneut erstellst.');const link=invitationUrl(data);$('submission-link-label').textContent=link?'Persönlicher Uploadlink':'Einmaliger Zugangsschlüssel';$('submission-link-value').value=link||data.token;$('submission-link-message').textContent=link?'Dieser persönliche Link wird nur jetzt angezeigt. Kopiere ihn und gib ihn ausschließlich an die zugehörige Person weiter.':'Der Zugang wurde erstellt, aber die öffentliche Upload-Adresse ist noch nicht eingerichtet. Der Schlüssel wird nur jetzt angezeigt. Noch keinen Link weitergeben.';$('submission-new-access').hidden=false;$('submission-access-label').value='';await loadSubmissionAccess();}
 catch(err){notify(err.message,true);}finally{button.disabled=false;}
});
$('submission-copy-link').addEventListener('click',async()=>{const value=$('submission-link-value').value;if(!value)return;try{await navigator.clipboard.writeText(value);notify('Kopiert. Nur an die zugehörige Person weitergeben.');}catch{$('submission-link-value').focus();$('submission-link-value').select();notify('Bitte den markierten Text kopieren.');}});
$('submission-hide-link').addEventListener('click',()=>{$('submission-link-value').value='';$('submission-new-access').hidden=true;});

function initSubmissionPage(){
 $('submission-page').hidden=false;document.title='Beleg einreichen · FT Sicherheitstechnik';
 const token=new URLSearchParams(window.location.hash.slice(1)).get('token')||'';let ready=false,busy=false;
 // The token is used only for this upload scope; no main-app APIs are initialized.
 async function submissionApi(path,options={}){const response=await fetch('api/'+path,{...options,headers:{'Content-Type':'application/json'},credentials:'omit',cache:'no-store',referrerPolicy:'no-referrer'});let result;try{result=await response.json();}catch{throw new Error('Die Verbindung konnte nicht bestätigt werden. Bitte versuche es später erneut.');}if(!response.ok)throw new Error(result.error||'Die Anfrage wurde nicht angenommen. Bitte wende dich an deinen Betrieb.');return result;}
 if(!/^[A-Za-z0-9_-]{43}$/.test(token)){$('submission-access-status').textContent='Dieser Zugang ist ungültig. Bitte lass dir einen neuen persönlichen Link geben.';return;}
 submissionApi('submissions/access',{method:'POST',body:JSON.stringify({token})}).then(result=>{if(result.valid!==true)throw new Error('Dieser Zugang ist ungültig oder wurde gesperrt. Bitte wende dich an deinen Betrieb.');ready=true;$('submission-access-status').hidden=true;$('submission-person').textContent='Uploadzugang: '+(result.label||'Mitarbeiter');$('submission-upload-form').hidden=false;}).catch(err=>{$('submission-access-status').textContent=err.message;$('submission-access-status').classList.add('error');});
 $('submission-upload-form').addEventListener('submit',async e=>{
  e.preventDefault();if(!ready||busy)return;const file=$('submission-file').files[0];if(!file)return;
  const types={pdf:'application/pdf',xml:'application/xml',jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png',tif:'image/tiff',tiff:'image/tiff'};const extension=file.name.split('.').pop().toLowerCase(),mime=types[extension];
  if(!mime){$('submission-upload-status').textContent='Bitte wähle PDF, XML, JPG, PNG oder TIFF. HEIC-Fotos bitte zunächst als JPG exportieren.';return;}
  if(!file.size||file.size>8*1024*1024){$('submission-upload-status').textContent='Die Datei ist leer oder größer als 8 MB. Bitte wähle eine kleinere, gut lesbare Datei.';return;}
  busy=true;$('submission-upload-button').disabled=true;$('submission-file').disabled=true;$('submission-upload-status').textContent='Dein Beleg wird übertragen. Bitte warte auf die Eingangsbestätigung …';
  try{const dataBase64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('Die Datei konnte nicht gelesen werden.'));reader.readAsDataURL(file);});const result=await submissionApi('submissions',{method:'POST',body:JSON.stringify({token,filename:file.name,mime,data_base64:dataBase64,project:$('submission-project').value.trim(),note:$('submission-note').value.trim()})});if(result.accepted!==true)throw new Error('Der Eingang konnte nicht bestätigt werden. Bitte frage im Betrieb nach, bevor du erneut hochlädst.');$('submission-receipt-id').textContent=result.receipt?'Eingangsnummer: '+result.receipt:'Eingang bestätigt.';$('submission-upload-form').reset();$('submission-upload-form').hidden=true;$('submission-receipt').hidden=false;$('submission-receipt').scrollIntoView({behavior:'auto',block:'nearest'});}
  catch(err){$('submission-upload-status').textContent=err.message+' Bei unklarem Übertragungsstatus bitte zuerst im Betrieb nachfragen.';}
  finally{busy=false;$('submission-upload-button').disabled=false;$('submission-file').disabled=false;}
 });
 $('submission-another').addEventListener('click',()=>{$('submission-receipt').hidden=true;$('submission-receipt-id').textContent='';$('submission-upload-status').textContent='';$('submission-upload-form').hidden=false;});
}
})();
