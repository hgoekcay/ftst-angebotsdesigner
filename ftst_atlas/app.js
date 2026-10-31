'use strict';
(() => {
const $ = id => document.getElementById(id);
if(/\/submit\/?$/.test(window.location.pathname)){initSubmissionPage();return;}
document.querySelector('.shell').hidden=false;
let activeView = 'chat', sending = false, noticeTimer, csrfToken = '';
const conversation = [];
let voiceEpoch=0;
let voiceStatus={}, voiceBusy=false, voiceRecording=null, voiceController=null, voiceAudio=null, voiceAudioURL=null, voiceStopButton=null;
const voiceButtons=[];
let dialogue=null;
let workflowCatalog=[],workflowStarting=false;
const labels = {chat:'CHAT',knowledge:'WISSEN',tasks:'AUFGABEN',mail:'E-MAILS',bookkeeping:'BUCHHALTUNG',system:'SYSTEM'};
function notify(message,error=false){const node=$('notice');node.textContent=message;node.className='notice'+(error?' error':'');node.hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>{node.hidden=true;},9000);}
async function api(path,options={}){
 if(options.method&&options.method!=='GET'&&!csrfToken){await loadStatus();if(!csrfToken)throw new Error('Die Sitzung ist noch nicht bereit. Bitte lade den Systemstatus neu.');}
 let response;
 try{response=await fetch('api/'+path,{...options,headers:{'Content-Type':'application/json',...(csrfToken?{'X-Atlas-CSRF':csrfToken}:{}),...(options.headers||{})},credentials:'same-origin',cache:'no-store'});}
 catch(error){if(error.name==='TypeError'||error.name==='AbortError')error.retryableRead=true;throw error;}
 let payload;
 try{payload=await response.json();}
 catch(error){if(error.name==='AbortError'||(response.ok&&error.name==='TypeError')){error.retryableRead=true;throw error;}throw Object.assign(new Error('Die Antwort des Servers konnte nicht gelesen werden. Bitte prüfe den Systemstatus.'),{status:response.status});}
 if(!response.ok){
  if(response.status===403){csrfToken='';throw Object.assign(new Error('Die Sitzungsfreigabe ist abgelaufen oder der Zugriff wurde abgelehnt. Bitte lade die Seite neu und prüfe vor einem erneuten Versuch, ob die Änderung bereits gespeichert wurde.'),{status:response.status});}
  throw Object.assign(new Error(payload.error||payload.message||'Die Anfrage konnte nicht abgeschlossen werden.'),{status:response.status});
 }
 return payload;
}
function element(tag,className,text){const n=document.createElement(tag);if(className)n.className=className;if(text!==undefined)n.textContent=text;return n;}
function switchView(view){if(!labels[view])return;if(dialogue&&view!=='chat')stopDialogue('Gespräch beim Seitenwechsel beendet.');activeView=view;document.querySelectorAll('.view').forEach(n=>{const selected=n.id==='view-'+view;n.hidden=!selected;n.classList.toggle('active',selected);});document.querySelectorAll('.nav-item').forEach(n=>{const selected=n.dataset.view===view;n.classList.toggle('active',selected);if(selected)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');});$('view-label').textContent=labels[view];if(view==='knowledge'){loadMemories();loadProfile();}if(view==='tasks'){loadTasks();loadJobs();loadWorkflows();}if(view==='mail')loadMailAccounts();if(view==='bookkeeping'){loadBookkeeping();loadSubmissionAccess();}if(view==='system')loadStatus();}
document.querySelectorAll('[data-view]').forEach(n=>n.addEventListener('click',()=>switchView(n.dataset.view)));
document.querySelector('.brand').addEventListener('click',e=>{e.preventDefault();switchView('chat');});
function addMessage(text,role,error=false){$('chat-intro').hidden=true;const article=element('article','message '+role+(error?' error':''));article.append(element('div','message-author',role==='user'?'Du':error?'Verbindungshinweis':'ATLAS'),element('div','message-text',text));if(role==='assistant'&&!error){const actions=element('div','message-tools');const remember=element('button','tiny-button','Als Wissen übernehmen');remember.type='button';remember.addEventListener('click',()=>{switchView('knowledge');resetMemoryForm();$('memory-text').value=text.slice(0,2000);$('memory-source').value='ATLAS-Entwurf – vom Nutzer zu prüfen';$('memory-text').focus();notify(text.length>2000?'Der Entwurf wurde auf 2.000 Zeichen gekürzt. Bitte prüfe und korrigiere ihn vor dem Speichern.':'Bitte prüfe und korrigiere den Entwurf vor dem Speichern.');});actions.append(remember);addVoicePlayback(actions,text);article.append(actions);}$('messages').append(article);article.scrollIntoView({behavior:'auto',block:'nearest'});return article;}
$('chat-form').addEventListener('submit',async e=>{e.preventDefault();if(sending||voiceBusy)return;const message=$('message').value.trim();if(!message)return;sending=true;addMessage(message,'user');$('message').value='';$('send-button').disabled=true;$('message').disabled=true;$('chat-progress').replaceChildren(element('span','thinking-dot'),document.createTextNode('ATLAS bearbeitet deinen Auftrag. Das Ergebnis bleibt unter Aufgaben abrufbar.'));$('chat-progress').hidden=false;$('chat-form').setAttribute('aria-busy','true');try{const job=await api('jobs',{method:'POST',body:JSON.stringify({message,mode:$('chat-mode').value,history:conversation.slice(-4).map(entry=>({role:entry.role,content:entry.content.slice(0,500)}))})});const data=await waitJob(job.id);const reply=data.reply||data.response||data.message;if(typeof reply!=='string'||!reply.trim())throw new Error('ATLAS hat keine verwertbare Antwort geliefert.');const article=addMessage(reply,'assistant');renderResult(article,data);conversation.push({role:'user',content:message},{role:'assistant',content:reply});if(conversation.length>4)conversation.splice(0,conversation.length-4);}catch(err){addMessage(err.message+' Ein angenommener Auftrag kann weiterlaufen. Bitte zuerst unter Aufgaben prüfen, bevor du erneut sendest.','assistant',true);}finally{sending=false;$('send-button').disabled=false;$('message').disabled=false;$('chat-progress').hidden=true;$('chat-form').removeAttribute('aria-busy');$('message').focus();updateVoiceControls();}});
$('message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('chat-form').requestSubmit();}});
document.querySelectorAll('[data-prompt]').forEach(n=>n.addEventListener('click',()=>{$('message').value=n.dataset.prompt;$('message').focus();}));
let memoryEditing=null, memoryRequest=0, taskKnowledgeIds=[];
function dateLabel(value){const date=new Date(value);return Number.isNaN(date.getTime())?'Datum unbekannt':date.toLocaleString('de-DE');}
function resetMemoryForm(){memoryEditing=null;$('memory-form').reset();$('memory-form-title').textContent='Wissen ergänzen';$('memory-save').textContent='Wissen speichern';$('memory-cancel').hidden=true;$('memory-edit-status').hidden=true;}
function editMemory(item){memoryEditing={id:item.id,revision:item.revision};$('memory-text').value=item.text;$('memory-source').value=item.source;$('memory-tags').value=(item.tags||[]).join(', ');$('memory-form-title').textContent='Wissen korrigieren';$('memory-save').textContent='Korrektur speichern';$('memory-cancel').hidden=false;$('memory-edit-status').hidden=false;$('memory-edit-status').textContent='Du bearbeitest Fassung '+item.revision+'. Die bisherige Fassung bleibt im Verlauf erhalten.';$('memory-text').focus();}
function setTaskKnowledge(ids,label=''){taskKnowledgeIds=ids;$('task-knowledge-selection').hidden=!ids.length;$('task-knowledge-label').textContent=label;}
async function loadMemories(){const request=++memoryRequest,query=$('memory-search').value.trim();$('memory-search-reset').hidden=!query;try{const data=await api('memories'+(query?'?q='+encodeURIComponent(query):''));if(request!==memoryRequest)return;const memories=Array.isArray(data)?data:(data.memories||data.items||[]);const list=$('memory-list');list.replaceChildren();$('memory-count').textContent=memories.length+(query?' Treffer':memories.length===1?' Eintrag':' Einträge');if(!memories.length)list.append(element('p','empty-state',query?'Keine passenden Einträge. Versuche einen anderen Suchbegriff.':'Noch keine Notizen gespeichert. Ergänze deinen ersten Eintrag, damit ATLAS darauf aufbauen kann.'));for(const item of memories){const card=element('article','memory-card');card.append(element('p','memory-text',item.text));const tags=element('div','knowledge-tags');for(const tag of item.tags||[])tags.append(element('span','tag',tag));card.append(tags);const meta=element('p','memory-meta',item.source+' · '+dateLabel(item.updated_at||item.created_at)+' · Fassung '+(item.revision||1));card.append(meta);const actions=element('div','knowledge-actions');const edit=element('button','tiny-button','Korrigieren');edit.type='button';edit.addEventListener('click',()=>editMemory(item));const task=element('button','tiny-button','Aufgabe dazu');task.type='button';task.addEventListener('click',()=>{switchView('tasks');setTaskKnowledge([item.id],'Verknüpftes Wissen: '+item.text.slice(0,140));$('task-title').focus();});const remove=element('button','delete-button','Löschen');remove.type='button';remove.setAttribute('aria-label','Wissenseintrag löschen');remove.addEventListener('click',async()=>{if(!window.confirm('Diesen Wissenseintrag einschließlich Verlauf dauerhaft löschen? Verknüpfte Aufgaben bleiben erhalten.'))return;remove.disabled=true;try{await api('memories/'+encodeURIComponent(item.id),{method:'DELETE'});if(memoryEditing?.id===item.id)resetMemoryForm();if(taskKnowledgeIds.includes(item.id))setTaskKnowledge([]);await loadMemories();notify('Wissenseintrag gelöscht.');}catch(err){notify(err.message,true);remove.disabled=false;}});actions.append(edit,task,remove);card.append(actions);const history=element('details','memory-history'),content=element('div');history.append(element('summary','','Änderungsverlauf'),content);history.addEventListener('toggle',async()=>{if(!history.open||history.dataset.loaded||history.dataset.loading)return;history.dataset.loading='true';content.textContent='Verlauf wird geladen …';try{const data=await api('memories/'+encodeURIComponent(item.id)+'/revisions');content.replaceChildren();for(const revision of data.revisions||[]){const entry=element('div','memory-revision');entry.append(element('p','quiet','Fassung '+revision.revision+' · '+dateLabel(revision.updated_at||revision.created_at)+' · '+revision.source),element('p','memory-text',revision.text),element('p','field-hint',(revision.tags||[]).join(' · ')));content.append(entry);}history.dataset.loaded='true';}catch(err){content.textContent=err.message;}finally{delete history.dataset.loading;}});card.append(history);list.append(card);}}catch(err){if(request===memoryRequest)$('memory-list').replaceChildren(element('p','empty-state',err.message));}}
$('memory-search-form').addEventListener('submit',e=>{e.preventDefault();loadMemories();});
$('memory-search-reset').addEventListener('click',()=>{$('memory-search').value='';loadMemories();});
$('memory-cancel').addEventListener('click',resetMemoryForm);
$('memory-form').addEventListener('submit',async e=>{e.preventDefault();const text=$('memory-text').value.trim(),source=$('memory-source').value.trim(),tags=$('memory-tags').value.split(',').map(s=>s.trim()).filter(Boolean);if(!text)return;if(tags.length>8||tags.some(tag=>tag.length>60)){notify('Bitte verwende höchstens 8 Schlagwörter mit jeweils maximal 60 Zeichen.',true);return;}const button=$('memory-save');button.disabled=true;$('memory-cancel').disabled=true;const editing=memoryEditing;try{await api('memories'+(editing?'/'+encodeURIComponent(editing.id):''),{method:editing?'PATCH':'POST',body:JSON.stringify({text,source,tags,...(editing?{revision:editing.revision}:{})})});resetMemoryForm();await loadMemories();notify(editing?'Korrektur gespeichert. Frühere Fassungen stehen im Verlauf.':'Gespeichert. ATLAS kann diese Notiz bei späteren lokalen Antworten berücksichtigen.');}catch(err){notify(err.message,true);}finally{button.disabled=false;$('memory-cancel').disabled=false;}});
async function loadTasks(){try{const data=await api('tasks');const tasks=Array.isArray(data)?data:(data.tasks||data.items||[]);const list=$('task-list');list.replaceChildren();const open=tasks.filter(t=>!t.done).length;$('task-count').textContent=String(open);$('tasks-summary').textContent=open+' offen · '+(tasks.length-open)+' erledigt';if(!tasks.length)list.append(element('p','empty-state','Platz für deinen nächsten Schritt. Lege oben deine erste Aufgabe an.'));for(const item of tasks){const card=element('article','task-card'),row=element('div','task-row'+(item.done?' done':''));const checkbox=element('input');checkbox.type='checkbox';checkbox.checked=!!item.done;checkbox.id='task-'+item.id;const label=element('label','',item.title);label.htmlFor=checkbox.id;checkbox.addEventListener('change',async()=>{checkbox.disabled=true;try{await api('tasks/'+encodeURIComponent(item.id),{method:'PATCH',body:JSON.stringify({done:checkbox.checked})});await loadTasks();}catch(err){checkbox.checked=!checkbox.checked;checkbox.disabled=false;notify(err.message,true);}});const remove=element('button','delete-button','Löschen');remove.type='button';remove.setAttribute('aria-label','Aufgabe löschen');remove.addEventListener('click',async()=>{if(!window.confirm('Diese Aufgabe dauerhaft löschen?'))return;remove.disabled=true;try{await api('tasks/'+encodeURIComponent(item.id),{method:'DELETE'});await loadTasks();notify('Aufgabe gelöscht.');}catch(err){notify(err.message,true);remove.disabled=false;}});row.append(checkbox,label,remove);card.append(row);if(item.knowledge_ids?.length){const details=element('details','task-linked-knowledge'),content=element('div');details.append(element('summary','','Verknüpftes Wissen ('+item.knowledge_ids.length+')'),content);details.addEventListener('toggle',async()=>{if(!details.open||details.dataset.loaded||details.dataset.loading)return;details.dataset.loading='true';content.textContent='Wissen wird geladen …';try{const data=await api('memories');content.replaceChildren();const linked=(data.memories||[]).filter(m=>item.knowledge_ids.includes(m.id));for(const memory of linked){const note=element('div','memory-revision');note.append(element('p','memory-text',memory.text),element('p','field-hint',memory.source+' · Fassung '+memory.revision));content.append(note);}if(linked.length!==item.knowledge_ids.length)content.append(element('p','field-hint','Ein verknüpfter Eintrag ist inzwischen nicht mehr verfügbar.'));details.dataset.loaded='true';}catch(err){content.textContent=err.message;}finally{delete details.dataset.loading;}});card.append(details);}list.append(card);}}catch(err){$('task-list').replaceChildren(element('p','empty-state',err.message));$('tasks-summary').textContent='Nicht erreichbar';}}
$('task-knowledge-clear').addEventListener('click',()=>setTaskKnowledge([]));
$('task-form').addEventListener('submit',async e=>{e.preventDefault();const title=$('task-title').value.trim();if(!title)return;const button=e.currentTarget.querySelector('button');button.disabled=true;try{await api('tasks',{method:'POST',body:JSON.stringify({title,knowledge_ids:taskKnowledgeIds})});$('task-title').value='';setTaskKnowledge([]);await loadTasks();notify('Aufgabe gespeichert.');}catch(err){notify(err.message,true);}finally{button.disabled=false;}});
async function loadStatus(){const short=$('status-short');try{const status=await api('status');csrfToken=status.csrf_token||'';voiceStatus=status.voice||{};updateVoiceControls();const available=status.ollama_reachable===true||status.ollama?.reachable===true||status.ollama?.available===true;const configuredOnly=(status.ollama_reachable===undefined||status.ollama_reachable===null)&&status.ollama?.reachable===undefined&&status.ollama?.available===undefined;short.classList.toggle('ok',available);short.lastElementChild.textContent=available?'Lokale KI erreichbar':configuredOnly?'ATLAS erreichbar':'KI nicht erreichbar';$('mail-status').textContent=status.mail_enabled?'Bereit zum Abruf.':'E-Mail-Zugriff noch nicht freigegeben. Die Verbindung wird in der ATLAS-Konfiguration eingerichtet.';$('online-status').textContent='OpenAI: '+(status.online?.reason||'nicht eingerichtet')+' · '+(status.online?.used||0)+' / '+(status.online?.limit||10)+' Anfragen heute (UTC).'+(status.online_share_profile?' Firmenprofil wird bei Online-Anfragen mitgegeben.':' Firmenprofil und gespeichertes Wissen werden nicht automatisch übertragen.');const details=$('system-details');details.replaceChildren();const rows=[['ATLAS','Erreichbar'],['HA-Benutzer-ID',status.ha_user_id||'Nicht verfügbar'],['Lokale KI',available?'Erreichbar':configuredOnly?'Bereitschaft noch nicht geprüft':'Nicht erreichbar'],['Modell',status.model||status.ollama?.model||'Nicht gemeldet'],['Version',status.version||'0.1'],['Betrieb','Lokal mit optionaler Online-Beratung'],['Online',status.online?.reason||'Nicht eingerichtet'],['Online-Modell',status.online?.model||'Nicht eingerichtet']];for(const [name,value] of rows)details.append(element('dt','',name),element('dd','',String(value)));if(status.warning)details.append(element('dt','','Hinweis'),element('dd','',String(status.warning)));}catch(err){short.classList.remove('ok');short.lastElementChild.textContent='Nicht erreichbar';$('system-details').replaceChildren(element('dt','','Verbindung'),element('dd','','Nicht erreichbar'));if(activeView==='system')notify(err.message,true);}}
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
// Only repeat status reads: a lost response must never resubmit a task.
async function readJob(id,state=null){
 const live=()=>!state||dialogueLive(state);
 for(let attempt=0;attempt<4;attempt++){
  if(!live())throw new Error('Gespräch beendet.');
  const controller=new AbortController();if(state)state.controller=controller;let timer;
  try{
   const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(Object.assign(new Error('Auftragsstatus antwortet nicht rechtzeitig.'),{name:'AbortError',retryableRead:true}));},30000);});
   const job=await Promise.race([api('jobs/'+encodeURIComponent(id),{signal:controller.signal}),timeout]);
   if(!live())throw new Error('Gespräch beendet.');
   if(attempt>0){if(state)dialogueStatus('ATLAS bearbeitet deine Anfrage. Das Mikrofon ist aus.');else $('chat-progress').replaceChildren(element('span','thinking-dot'),document.createTextNode('ATLAS bearbeitet deinen Auftrag. Das Ergebnis bleibt unter Aufgaben abrufbar.'));}
   return job;
  }catch(error){
   if(!live())throw error;
   const transient=error.retryableRead===true||error.status===408||error.status===429||(error.status>=500&&error.status<=599);
   if(!transient||attempt===3)throw error;
   const message='Verbindung kurz unterbrochen. Ich hole die Antwort erneut ab ('+(attempt+1)+'/3). Dein Auftrag wird nicht erneut gestartet.';
   if(state)dialogueStatus(message);else $('chat-progress').textContent=message;
  }finally{clearTimeout(timer);if(state&&state.controller===controller)state.controller=null;}
  await new Promise(resolve=>setTimeout(resolve,2000));
 }
}
async function waitJob(id){
 for(let n=0;n<240;n++){
  await new Promise(resolve=>setTimeout(resolve,1500));
  const job=await readJob(id);
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
   renderJobSteps(card,job);
   if(job.status==='completed'){const detail=element('details');detail.append(element('summary','','Ergebnis ansehen'),element('div','message-text',job.result?.reply||''));if(!job.result?.workflow)renderResult(detail,job.result||{});else renderWorkflowArtifact(detail,job.result);card.append(detail);}
   if(job.error)card.append(element('p','message-text',job.error));list.append(card);
  }
  if(!data.jobs.length)list.append(element('p','empty-state','Noch keine Hintergrundaufträge.'));
  if(activeView==='tasks'&&data.jobs.some(j=>['queued','running'].includes(j.status)))jobsTimer=setTimeout(loadJobs,3000);
 }catch(err){$('job-list').replaceChildren(element('p','empty-state',err.message));}
}
$('refresh-jobs').addEventListener('click',loadJobs);

function selectWorkflow(){
 const choice=workflowCatalog.find(w=>w.id===$('workflow-kind').value);
 $('workflow-description').textContent=choice?.description||'Kein Ablauf verfügbar.';
 $('workflow-month-wrap').hidden=!choice?.requires_month;$('workflow-month').required=!!choice?.requires_month;
 $('workflow-start').disabled=workflowStarting||!choice?.enabled;
}
async function loadWorkflows(){
 try{const data=await api('workflows/catalog');workflowCatalog=Array.isArray(data.workflows)?data.workflows:[];const select=$('workflow-kind'),previous=select.value;select.replaceChildren();for(const item of workflowCatalog){const option=element('option','',item.title+(item.enabled?'':' · nicht freigegeben'));option.value=item.id;option.disabled=!item.enabled;select.append(option);}select.value=workflowCatalog.some(w=>w.id===previous&&w.enabled)?previous:(workflowCatalog.find(w=>w.enabled)?.id||'');select.disabled=!workflowCatalog.some(w=>w.enabled);if(!$('workflow-month').value)$('workflow-month').value=new Date().toISOString().slice(0,7);selectWorkflow();}
 catch(err){$('workflow-description').textContent=err.message;$('workflow-start').disabled=true;}
}
$('workflow-kind').addEventListener('change',selectWorkflow);
$('workflow-form').addEventListener('submit',async e=>{
 e.preventDefault();if(workflowStarting)return;const choice=workflowCatalog.find(w=>w.id===$('workflow-kind').value);if(!choice?.enabled)return;
 const body={workflow:choice.id};if(choice.requires_month){body.month=$('workflow-month').value;if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(body.month)){notify('Bitte einen gültigen Monat auswählen.',true);return;}}
 workflowStarting=true;selectWorkflow();$('workflow-status').textContent='Ablauf wird angenommen …';
 try{await api('workflows',{method:'POST',body:JSON.stringify(body)});$('workflow-status').textContent='Gestartet. Die einzelnen Schritte und das Ergebnis stehen unter Hintergrundaufträge.';await loadJobs();}
 catch(err){$('workflow-status').textContent=err.message+' Bitte zuerst die Hintergrundaufträge prüfen, bevor du erneut startest.';await loadJobs();}
 finally{workflowStarting=false;selectWorkflow();}
});
function renderJobSteps(card,job){
 if(!Array.isArray(job.steps)||!job.steps.length)return;const steps=element('ol','workflow-steps');
 const labels={pending:'Ausstehend',running:'Läuft',completed:'Erledigt',failed:'Fehlgeschlagen'};
 for(const step of job.steps){const item=element('li','',step.label+' · '+(labels[step.status]||'Unbekannt'));if(step.detail)item.append(element('small','',step.detail));steps.append(item);}card.append(steps);
}
function renderWorkflowArtifact(container,result){
 if(result.incomplete)container.append(element('p','workflow-warning','Unvollständige Daten: Hinweise im Ergebnis prüfen. Dieser Export ist keine abgeschlossene Buchhaltung.'));
 const artifact=result.artifact;if(!artifact||typeof artifact.url!=='string'||!/^api\/workflows\/[A-Za-z0-9_-]+\/download$/.test(artifact.url))return;
 const link=element('a','workflow-artifact','Export herunterladen');link.href=artifact.url;link.download=artifact.filename||'atlas-export.zip';container.append(link,element('p','field-hint','Nur für dein Benutzerkonto. Exporte werden zeitlich und mengenmäßig begrenzt aufbewahrt.'));
}
function recordingSupported(){return typeof navigator!=='undefined'&&!!navigator.mediaDevices?.getUserMedia&&typeof MediaRecorder!=='undefined';}
function updateVoiceControls(){
 const enabled=voiceStatus.enabled===true,supported=recordingSupported();if(dialogue&&!enabled){stopDialogue('Sprachfreigabe nicht mehr verfügbar.');return;}$('voice-file').disabled=!enabled||voiceBusy||sending;$('voice-record').disabled=!enabled||!supported||sending||!!dialogue||(voiceBusy&&!voiceRecording);
 $('voice-record').textContent=voiceRecording?'Aufnahme beenden':'Sprache aufnehmen';$('voice-cancel').hidden=!voiceBusy||!!dialogue;
 $('dialogue-start').disabled=!enabled||!supported||!(window.AudioContext||window.webkitAudioContext)||voiceBusy||sending;
 $('dialogue-start').hidden=!!dialogue;$('dialogue-stop').hidden=!dialogue;
 $('chat-mode').disabled=!!dialogue;
 if(!voiceBusy)$('voice-status').textContent=!enabled?(voiceStatus.reason||'Lokale Sprache ist nicht freigegeben.'):!supported?'Aufnahme benötigt einen unterstützten Browser und HTTPS.':'Lokal transkribieren · maximal 60 Sekunden. Text vor dem Senden prüfen.';
 for(const button of voiceButtons){button.disabled=!enabled||!!dialogue;button.title=enabled?'Lokal mit Piper vorlesen':voiceStatus.reason||'Lokale Sprache ist nicht freigegeben.';}
}
function stopVoicePlayback(){if(voiceStopButton){voiceStopButton.hidden=true;voiceStopButton=null;}if(voiceAudio){voiceAudio.pause();voiceAudio.src='';voiceAudio=null;}if(voiceAudioURL){URL.revokeObjectURL(voiceAudioURL);voiceAudioURL=null;}}
async function voiceRequest(path,body,contentType,stillActive=()=>true){
 if(!csrfToken)await loadStatus();if(!stillActive())throw Object.assign(new Error('Abgebrochen.'),{name:'AbortError'});if(!csrfToken)throw new Error('Sitzung nicht bereit. Bitte Systemstatus neu laden.');
 const controller=new AbortController();voiceController=controller;const timeout=setTimeout(()=>controller.abort(),path==='transcribe'?165000:130000);
 try{const response=await fetch('api/voice/'+path,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':contentType,'X-Atlas-CSRF':csrfToken},body,signal:controller.signal});if(!response.ok){let data={};try{data=await response.json();}catch{}throw new Error(data.error||'Lokale Sprachverarbeitung nicht verfügbar.');}return path==='transcribe'?await response.json():await response.blob();}
 finally{clearTimeout(timeout);if(voiceController===controller)voiceController=null;}
}
function endRecording(discard=false){const state=voiceRecording;if(!state)return;state.discard=state.discard||discard;clearTimeout(state.timer);state.stream.getTracks().forEach(track=>track.stop());if(state.recorder.state!=='inactive')state.recorder.stop();}
function finishVoice(){voiceBusy=false;voiceRecording=null;$('message').disabled=sending;$('send-button').disabled=sending;updateVoiceControls();}
$('voice-record').addEventListener('click',async()=>{
 if(voiceRecording){endRecording();return;}if(voiceBusy||sending||!voiceStatus.enabled||!recordingSupported())return;
 stopVoicePlayback();const epoch=++voiceEpoch;voiceBusy=true;updateVoiceControls();$('message').disabled=true;$('send-button').disabled=true;$('voice-status').textContent='Mikrofonfreigabe wird angefragt …';let stream;
 try{
  stream=await navigator.mediaDevices.getUserMedia({audio:true});if(epoch!==voiceEpoch||!voiceBusy){stream.getTracks().forEach(t=>t.stop());return;}
  const mime=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(type=>MediaRecorder.isTypeSupported(type));if(!mime)throw new Error('Dieser Browser bietet kein unterstütztes Aufnahmeformat.');
  const recorder=new MediaRecorder(stream,{mimeType:mime}),state={recorder,stream,chunks:[],bytes:0,discard:false,timer:null};voiceRecording=state;
  recorder.addEventListener('dataavailable',event=>{if(state.discard||!event.data.size)return;state.bytes+=event.data.size;if(state.bytes>5*1024*1024){state.discard=true;notify('Aufnahme überschreitet 5 MiB. Bitte kürzer aufnehmen.',true);endRecording(true);return;}state.chunks.push(event.data);});
  recorder.addEventListener('error',()=>{if(epoch!==voiceEpoch)return;notify('Die Aufnahme ist fehlgeschlagen.',true);endRecording(true);finishVoice();});
  recorder.addEventListener('stop',async()=>{
   clearTimeout(state.timer);state.stream.getTracks().forEach(t=>t.stop());if(epoch!==voiceEpoch)return;voiceRecording=null;updateVoiceControls();
   try{if(state.discard||!voiceBusy||epoch!==voiceEpoch)return;if(!state.bytes)throw new Error('Keine Audiodaten aufgenommen.');$('voice-status').textContent='Wird lokal transkribiert …';const data=await voiceRequest('transcribe',new Blob(state.chunks,{type:mime}),mime);if(!voiceBusy||epoch!==voiceEpoch)return;if(typeof data.text!=='string'||!data.text.trim())throw new Error('Kein Text erkannt.');const combined=[$('message').value.trim(),data.text.trim()].filter(Boolean).join('\n');if(combined.length>2000)throw new Error('Text und vorhandener Entwurf überschreiten 2.000 Zeichen. Bitte den Entwurf kürzen und erneut aufnehmen.');$('message').value=combined;notify('Transkript eingefügt. Bitte prüfen und selbst senden.');}
   catch(err){if(voiceBusy)notify(err.name==='AbortError'?'Sprachverarbeitung abgebrochen oder Zeitlimit erreicht.':err.message,true);}
   finally{if(epoch===voiceEpoch){finishVoice();$('message').focus();}}
  });
  recorder.start(250);state.timer=setTimeout(()=>endRecording(),60000);updateVoiceControls();$('voice-status').textContent='Aufnahme läuft · endet spätestens nach 60 Sekunden.';
 }catch(err){if(stream)stream.getTracks().forEach(t=>t.stop());if(epoch!==voiceEpoch)return;finishVoice();notify(err.name==='NotAllowedError'?'Mikrofon nicht freigegeben. Du kannst weiterhin tippen.':err.message,true);}
});
$('voice-cancel').addEventListener('click',()=>{voiceEpoch++;endRecording(true);if(voiceController)voiceController.abort();stopVoicePlayback();finishVoice();notify('Aufnahme verworfen. Es wurde keine Chatnachricht gesendet.');});
$('voice-file').addEventListener('change',async()=>{
 const file=$('voice-file').files?.[0];$('voice-file').value='';if(!file||voiceBusy||sending||!voiceStatus.enabled)return;
 const mime=file.type.split(';')[0];if(!['audio/wav','audio/x-wav','audio/mp4','audio/ogg','audio/webm'].includes(mime)){notify('Bitte WAV, MP4, OGG oder WebM auswählen.',true);return;}
 if(!file.size||file.size>5*1024*1024){notify('Audiodatei muss zwischen 1 Byte und 5 MiB groß sein.',true);return;}
 stopVoicePlayback();const epoch=++voiceEpoch;voiceBusy=true;updateVoiceControls();$('message').disabled=true;$('send-button').disabled=true;$('voice-status').textContent='Datei wird lokal geprüft und transkribiert · maximal 60 Sekunden.';
 try{const data=await voiceRequest('transcribe',file,file.type);if(epoch!==voiceEpoch)return;if(typeof data.text!=='string'||!data.text.trim())throw new Error('Kein Text erkannt.');const combined=[$('message').value.trim(),data.text.trim()].filter(Boolean).join('\n');if(combined.length>2000)throw new Error('Text und Entwurf überschreiten 2.000 Zeichen. Bitte Entwurf kürzen.');$('message').value=combined;notify('Transkript eingefügt. Bitte prüfen und selbst senden.');}
 catch(err){if(epoch===voiceEpoch)notify(err.name==='AbortError'?'Sprachverarbeitung abgebrochen oder Zeitlimit erreicht.':err.message,true);}
 finally{if(epoch===voiceEpoch){finishVoice();$('message').focus();}}
});
function addVoicePlayback(actions,text){
 const button=element('button','tiny-button','Vorlesen'),stop=element('button','tiny-button','Vorlesen stoppen');button.type=stop.type='button';stop.hidden=true;voiceButtons.push(button);button.disabled=voiceStatus.enabled!==true||!!dialogue;
 button.addEventListener('click',async()=>{if(!voiceStatus.enabled||voiceBusy)return;if(text.length>2000){notify('Vorlesen ist auf 2.000 Zeichen begrenzt.',true);return;}stopVoicePlayback();const epoch=++voiceEpoch;voiceBusy=true;updateVoiceControls();button.disabled=true;stop.hidden=false;voiceStopButton=stop;$('voice-status').textContent='Sprachausgabe wird lokal erstellt …';
 try{const blob=await voiceRequest('synthesize',JSON.stringify({text}),'application/json');if(!voiceBusy||epoch!==voiceEpoch)return;if(blob.type.split(';')[0]!=='audio/wav')throw new Error('Ungültige Audioantwort.');voiceAudioURL=URL.createObjectURL(blob);voiceAudio=document.createElement('audio');voiceAudio.src=voiceAudioURL;voiceAudio.addEventListener('ended',()=>{stopVoicePlayback();stop.hidden=true;});await voiceAudio.play();}
 catch(err){if(epoch!==voiceEpoch)return;stopVoicePlayback();stop.hidden=true;if(voiceBusy)notify(err.name==='AbortError'?'Vorlesen abgebrochen oder Zeitlimit erreicht.':err.message,true);}
 finally{if(epoch===voiceEpoch)finishVoice();}});
 stop.addEventListener('click',()=>{voiceEpoch++;if(voiceController)voiceController.abort();stopVoicePlayback();finishVoice();stop.hidden=true;});actions.append(button,stop);
}
if(typeof window.addEventListener==='function')window.addEventListener('pagehide',()=>{if(dialogue)stopDialogue('Gespräch beendet.');voiceEpoch++;endRecording(true);if(voiceController)voiceController.abort();voiceBusy=false;stopVoicePlayback();});


// An explicitly started, half-duplex conversation. No microphone or commands on load.
function dialogueLive(state){return dialogue===state&&!state.stopped;}
function dialogueStatus(text){$('dialogue-status').textContent=text;}
function releaseDialogueCapture(state){
 clearTimeout(state.listenTimer);clearTimeout(state.limitTimer);state.finishCapture=null;$('dialogue-answer').hidden=true;
 if(state.source){state.source.disconnect();state.source=null;}
 if(state.stream){state.stream.getTracks().forEach(t=>t.stop());state.stream=null;}
}
function stopDialogue(reason='Gespräch beendet.'){
 const state=dialogue;if(!state)return;state.stopped=true;dialogue=null;voiceEpoch++;
 clearTimeout(state.sessionTimer);clearTimeout(state.waitTimer);clearTimeout(state.playbackTimer);releaseDialogueCapture(state);
 if(state.playback){const source=state.playback;state.playback=null;try{source.stop();}catch{}try{source.disconnect();}catch{}}
 if(state.recorder&&state.recorder.state!=='inactive')state.recorder.stop();
 if(state.controller)state.controller.abort();if(voiceController)voiceController.abort();
 stopVoicePlayback();if(state.context)state.context.close().catch(()=>{});
 finishVoice();dialogueStatus(reason+(state.submitted?' Bereits übermittelte Aufträge können weiterlaufen. Ergebnis unter Aufgaben prüfen.':''));
}
function dialogueFailure(state,error){
 if(!dialogueLive(state))return;
 const messages={NotAllowedError:'Mikrofon oder Audio nicht freigegeben. Bitte die Berechtigung für diese Seite prüfen und Gespräch erneut starten.',NotFoundError:'Kein Mikrofon gefunden. Bitte ein Mikrofon anschließen oder ATLAS auf deinem Handy öffnen.',NotReadableError:'Das Mikrofon wird bereits verwendet oder ist nicht erreichbar. Bitte andere Audio-Apps schließen.',AbortError:'Sprachverarbeitung abgebrochen oder Zeitlimit erreicht. Bitte Gespräch erneut starten.'};
 const message=messages[error.name]||error.message||'Gespräch unterbrochen.';stopDialogue(message);notify(message,true);
}
async function dialogueBounded(state,promise,ms,message){
 let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(message)),ms);state.waitTimer=timer;})]);}
 finally{clearTimeout(timer);if(state.waitTimer===timer)state.waitTimer=null;}
}
async function speakDialogue(state,text,greeting=false){
 if(!dialogueLive(state))return;
 dialogueStatus(greeting?'ATLAS startet die Begrüßung. Bitte kurz warten …':'Die gesprochene Antwort wird lokal vorbereitet …');
 const blob=await dialogueBounded(state,voiceRequest('synthesize',JSON.stringify({text}),'application/json',()=>dialogueLive(state)),45000,'Die lokale Sprachausgabe antwortet nicht rechtzeitig. Bitte Piper prüfen und Gespräch erneut starten.');
 if(!dialogueLive(state))return;if(blob.type.split(';')[0]!=='audio/wav')throw new Error('Ungültige Audioantwort.');
 const buffer=await dialogueBounded(state,state.context.decodeAudioData(await blob.arrayBuffer()),10000,'Audio konnte nicht geöffnet werden. Bitte Gespräch erneut starten.');
 if(!dialogueLive(state))return;
 if(state.context.state!=='running')throw new Error('Audio wurde vom Browser angehalten. Bitte Gespräch erneut starten und die Audiofreigabe prüfen.');
 if(!Number.isFinite(buffer.duration)||buffer.duration<=0||buffer.duration>120)throw new Error('Ungültige Länge der Sprachausgabe.');
 const source=state.context.createBufferSource();source.buffer=buffer;source.connect(state.context.destination);state.playback=source;
 source.onended=()=>{if(!dialogueLive(state)||state.playback!==source)return;state.playback=null;clearTimeout(state.playbackTimer);source.disconnect();listenDialogue(state).catch(error=>dialogueFailure(state,error));};
 state.playbackTimer=setTimeout(()=>dialogueFailure(state,new Error('Die Wiedergabe wurde angehalten. Bitte Gespräch erneut starten.')),Math.ceil(buffer.duration*1000)+5000);
 dialogueStatus(greeting?'Hallo, ich bin ATLAS. Gleich kannst du sprechen.':'ATLAS spricht. Das Mikrofon ist aus.');source.start();
}

function dialogueRequestId(){
 if(typeof crypto!=='undefined'&&typeof crypto.randomUUID==='function')return crypto.randomUUID();
 if(typeof crypto==='undefined'||typeof crypto.getRandomValues!=='function')throw new Error('Dieser Browser unterstützt keine sicheren Auftragskennungen.');
 return Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('');
}
async function dialogueApi(state,path,options={}){
 if(!dialogueLive(state))throw new Error('Gespräch beendet.');
 const controller=new AbortController();state.controller=controller;const timer=setTimeout(()=>controller.abort(),30000);
 try{return await api(path,{...options,signal:controller.signal});}
 finally{clearTimeout(timer);if(state.controller===controller)state.controller=null;}
}
async function dialogueTurn(state,audio,mime){
 if(!dialogueLive(state))return;
 try{
  dialogueStatus('Ich schreibe deine Aufnahme lokal mit …');
  const transcription=await voiceRequest('transcribe',audio,mime,()=>dialogueLive(state));if(!dialogueLive(state))return;
  const message=typeof transcription.text==='string'?transcription.text.trim():'';
  if(!message||message.length>2000)throw new Error('Keine passende Sprache erkannt. Bitte Gespräch neu starten.');
  // A spoken stop only closes the conversation; it is never dispatched as a job.
  if(/^(?:stopp?|gespräch beenden|atlas stopp?)[.!?]*$/i.test(message)){stopDialogue('Gespräch auf deinen Wunsch beendet.');return;}
  addMessage(message,'user');dialogueStatus('ATLAS bearbeitet deine Anfrage. Das Mikrofon ist aus.');
  state.submitted=true;
  const job=await dialogueApi(state,'voice/turn',{method:'POST',body:JSON.stringify({message,mode:state.mode,history:conversation.slice(-4).map(entry=>({role:entry.role,content:entry.content.slice(0,500)})),request_id:dialogueRequestId()})});
  if(!dialogueLive(state))return;
  let data;
  for(let n=0;n<240&&dialogueLive(state);n++){
   await new Promise(resolve=>setTimeout(resolve,1500));if(!dialogueLive(state))return;
   const current=await readJob(job.id,state);if(!dialogueLive(state))return;
   if(current.status==='failed')throw new Error(current.error||'Auftrag fehlgeschlagen.');
   if(current.status==='completed'){data=current.result;break;}
  }
  if(!dialogueLive(state))return;if(!data)throw new Error('Der Auftrag läuft noch. Bitte unter Aufgaben prüfen.');
  const reply=data.reply||data.response||data.message;if(typeof reply!=='string'||!reply.trim())throw new Error('Keine verwertbare Antwort erhalten.');
  state.submitted=false;const article=addMessage(reply,'assistant');renderResult(article,data);if(data.workflow)renderWorkflowArtifact(article,data);
  conversation.push({role:'user',content:message},{role:'assistant',content:reply});if(conversation.length>4)conversation.splice(0,conversation.length-4);
  if(data.action==='task_created')loadTasks();
  // Long answers remain complete on screen; the spoken excerpt is explicitly labelled.
  const spoken=reply.length>1900?reply.slice(0,1800)+' … Die vollständige Antwort steht im Chat.':reply;
  await speakDialogue(state,spoken);
 }catch(error){dialogueFailure(state,error);}
}
async function listenDialogue(state){
 if(!dialogueLive(state))return;
 dialogueStatus('Mikrofon wird geöffnet …');
 const pending=navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}}).then(stream=>{if(!dialogueLive(state))stream.getTracks().forEach(track=>track.stop());return stream;});
 const stream=await dialogueBounded(state,pending,30000,'Mikrofonfreigabe fehlt. Bitte die Mikrofonabfrage bestätigen oder die Berechtigung für diese Seite prüfen.');
 if(!dialogueLive(state)){stream.getTracks().forEach(t=>t.stop());return;}
 state.stream=stream;
 await dialogueBounded(state,state.context.resume(),8000,'Audioerkennung konnte nach der Mikrofonfreigabe nicht gestartet werden. Bitte Gespräch erneut starten.');
 if(!dialogueLive(state))return;
 if(state.context.state!=='running')throw new Error('Audioerkennung ist angehalten. Bitte Gespräch erneut starten.');
 const mime=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(type=>MediaRecorder.isTypeSupported(type));
 if(!mime)throw new Error('Kein unterstütztes Aufnahmeformat.');
 const recorder=new MediaRecorder(stream,{mimeType:mime});state.recorder=recorder;
 const analyser=state.context.createAnalyser();analyser.fftSize=2048;state.source=state.context.createMediaStreamSource(stream);state.source.connect(analyser);
 const samples=new Float32Array(analyser.fftSize),chunks=[];let bytes=0,voicedMs=0,silentMs=0,elapsedMs=0,ended=false,manual=false;
 function finish(byButton=false){if(ended||!dialogueLive(state))return;if(byButton&&elapsedMs<500){dialogueStatus('Bitte erst kurz sprechen, dann „Jetzt antworten“ drücken.');return;}manual=byButton;ended=true;releaseDialogueCapture(state);if(recorder.state!=='inactive')recorder.stop();}
 recorder.addEventListener('dataavailable',event=>{if(!dialogueLive(state)||!event.data.size)return;bytes+=event.data.size;if(bytes>5*1024*1024){stopDialogue('Aufnahme zu groß. Bitte kürzer sprechen.');return;}chunks.push(event.data);});
 recorder.addEventListener('error',()=>dialogueFailure(state,new Error('Die Aufnahme ist fehlgeschlagen.')));
 recorder.addEventListener('stop',()=>{if(!dialogueLive(state)||state.recorder!==recorder)return;releaseDialogueCapture(state);state.recorder=null;if((!manual&&voicedMs<450)||!bytes){stopDialogue('Keine Sprache erkannt. Gespräch beendet.');return;}dialogueTurn(state,new Blob(chunks,{type:mime}),mime);});
 function detect(){
  if(!dialogueLive(state)||ended)return;
  if(state.context.state==='suspended'){stopDialogue('Audioerkennung wurde angehalten. Bitte Gespräch erneut starten.');return;}
  analyser.getFloatTimeDomainData(samples);let sum=0;for(const sample of samples)sum+=sample*sample;const rms=Math.sqrt(sum/samples.length);elapsedMs+=100;
  if(rms>=0.018){voicedMs+=100;silentMs=0;}else silentMs+=100;
  if(voicedMs>=450&&silentMs>=2000){finish();return;}
  if(voicedMs<450&&elapsedMs>=15000){stopDialogue('15 Sekunden ohne Sprache. Gespräch beendet.');return;}
  state.listenTimer=setTimeout(detect,100);
 }
 recorder.start(250);state.finishCapture=()=>finish(true);$('dialogue-answer').hidden=false;state.limitTimer=setTimeout(()=>finish(),60000);state.listenTimer=setTimeout(detect,100);
 dialogueStatus('Ich höre zu. Sprich jetzt. Nach einer Pause antworte ich; alternativ „Jetzt antworten“ drücken.');
}
$('dialogue-start').addEventListener('click',async()=>{
 if(dialogue||voiceBusy||sending||!voiceStatus.enabled||!recordingSupported())return;
 if($('message').value.trim()){notify('Bitte den vorhandenen Text zuerst senden oder entfernen.',true);return;}
 const Context=window.AudioContext||window.webkitAudioContext;if(!Context)return;
 stopVoicePlayback();const state={mode:$('chat-mode').value,stopped:false,submitted:false};dialogue=state;voiceBusy=true;voiceEpoch++;updateVoiceControls();$('message').disabled=true;$('send-button').disabled=true;
 state.sessionTimer=setTimeout(()=>{if(dialogueLive(state))stopDialogue('Gespräch nach zehn Minuten beendet.');},600000);
 dialogueStatus('Audio wird aktiviert. Bitte kurz warten …');
 try{
  state.context=new Context();
  const resumed=state.context.resume(); // Must run directly in the user's click.
  if(typeof state.context.addEventListener==='function')state.context.addEventListener('statechange',()=>{if(dialogueLive(state)&&state.playback&&state.context.state!=='running')dialogueFailure(state,new Error('Die Audiowiedergabe wurde unterbrochen. Bitte Gespräch erneut starten.'));});
  await dialogueBounded(state,resumed,8000,'Audio konnte nicht aktiviert werden. Bitte die Seite im Browser öffnen und Gespräch erneut starten.');
  if(dialogueLive(state))await speakDialogue(state,'Hallo, ich bin Atlas. Gleich kannst du sprechen.',true);
 }catch(error){dialogueFailure(state,error);}
});
$('dialogue-answer').addEventListener('click',()=>{if(dialogue?.finishCapture)dialogue.finishCapture();});
$('dialogue-stop').addEventListener('click',()=>stopDialogue());
if(typeof document.addEventListener==='function')document.addEventListener('visibilitychange',()=>{if(document.hidden&&dialogue)stopDialogue('Gespräch im Hintergrund beendet.');});


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
