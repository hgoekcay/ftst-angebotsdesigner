/* ATLAS Front Desk: configured calendar + GPT-Live WebRTC. Keys never enter this file. */
'use strict';
(() => {
 const host=document.getElementById('view-chat');
 if(!host||/\/submit\/?$/.test(location.pathname))return;
 const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text)node.textContent=text;if(cls)node.className=cls;return node;};
 const panel=el('details',null,'frontdesk card');panel.id='frontdesk';
 const heading=el('summary','Termine mit ATLAS');panel.append(heading);
 const body=el('div',null,'frontdesk-body');panel.append(body);
 const mode=el('span','FT SICHERHEITSTECHNIK','section-kicker'),notice=el('p','Kalenderverbindung wird geprüft …');body.append(mode,el('h2','Ein Gespräch. Dein nächster Termin.'),notice);
 const actions=el('div',null,'frontdesk-actions'),start=el('button','Termin-Gespräch starten','primary'),stop=el('button','Gespräch beenden','secondary');start.type=stop.type='button';stop.disabled=true;start.disabled=true;actions.append(start,stop);body.append(actions);
 const status=el('p','Verfügbarkeit wird geladen …','field-hint');status.setAttribute('role','status');status.setAttribute('aria-live','polite');body.append(status);
 body.append(el('p','Beim Start werden deine Stimme und Termindetails an OpenAI übertragen. GPT-Live und das Backend verursachen API-Kosten. Bestätige den Vorschlag unten ausdrücklich vor dem Speichern.','field-hint'));
 const audio=el('audio');audio.autoplay=true;audio.controls=true;audio.hidden=true;audio.setAttribute('aria-label','ATLAS-Sprachausgabe');body.append(audio);
 const transcript=el('div',null,'frontdesk-transcript');transcript.setAttribute('role','log');transcript.setAttribute('aria-label','Gesprächsverlauf');body.append(transcript);
 const form=el('form',null,'frontdesk-form');const nameLabel=el('label','Name für den Termin'),name=el('input');name.id='frontdesk-name';name.maxLength=100;name.required=true;name.autocomplete='name';nameLabel.htmlFor=name.id;
 const dayLabel=el('label','Tag wählen'),day=el('select');day.id='frontdesk-day';dayLabel.htmlFor=day.id;
 form.append(nameLabel,name,dayLabel,day);const slots=el('div',null,'frontdesk-slots');slots.setAttribute('aria-label','Freie Termine');form.append(slots);body.append(form);
 const proposal=el('div',null,'frontdesk-proposal');proposal.hidden=true;body.append(proposal);
 const booked=el('div',null,'frontdesk-bookings'),bookingHeading=el('h3','Termine');body.append(bookingHeading,booked);
 const refresh=el('button','Kalender aktualisieren','secondary');refresh.type='button';body.append(refresh);
 const anchor=document.getElementById('dialogue-panel');if(anchor?.parentNode===host)anchor.after(panel);else host.append(panel);
 let token='',calendar=null,run=null,mutationBusy=false,loadSequence=0;
 const format=value=>new Intl.DateTimeFormat('de-DE',{timeZone:'Europe/Berlin',dateStyle:'medium',timeStyle:'short'}).format(new Date(value));
 const time=value=>new Intl.DateTimeFormat('de-DE',{timeZone:'Europe/Berlin',hour:'2-digit',minute:'2-digit'}).format(new Date(value));
 const dayKey=value=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Berlin',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
 async function api(path,data,extra={}){
  if(data!==undefined&&!token){const r=await fetch('api/status',{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw Error('ATLAS-Sitzung nicht verfügbar. Seite neu laden.');token=(await r.json()).csrf_token||'';if(!token)throw Error('ATLAS-Sitzung nicht bereit.');}
  const response=await fetch('api/frontdesk/'+path,{method:data===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',...extra,headers:{'Content-Type':'application/json',...(token?{'X-Atlas-CSRF':token}:{})},...(data!==undefined?{body:JSON.stringify(data)}:{})});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Termin-Anfrage fehlgeschlagen.');return result;
 }
 function announce(text){status.textContent=text;}
 function line(role,text){if(!text)return;let row=transcript.lastElementChild;if(!row||row.dataset.role!==role){row=el('p');row.dataset.role=role;row.append(el('strong',role==='user'?'Du: ':'ATLAS: '),el('span'));transcript.append(row);}row.lastElementChild.textContent=(row.lastElementChild.textContent+text).slice(-6000);while(transcript.children.length>30)transcript.firstElementChild.remove();}
 function render(state){
  calendar=state;const demo=state.demo!==false;heading.textContent=demo?'Termine mit ATLAS · Demo':'Termine mit ATLAS · Firmenkalender';mode.textContent=demo?'FT SICHERHEITSTECHNIK · DEMO':'FT SICHERHEITSTECHNIK · FIRMENKALENDER';notice.textContent=state.notice||(demo?'Demo-Kalender: keine echten Kundentermine und keine externen Einladungen.':'Termine werden nach deiner Bestätigung im verbundenen Kalender gespeichert. Alle Zeiten: Europe/Berlin.');nameLabel.textContent=demo?'Name für den Demo-Termin':'Name für den Termin';bookingHeading.textContent=demo?'Bestätigte Demo-Termine':'Buchungen und Buchungsstatus';const available=state.available||[];const previous=day.value;day.replaceChildren();for(const value of [...new Set(available.map(s=>dayKey(s.start)))]){const option=el('option',new Intl.DateTimeFormat('de-DE',{timeZone:'Europe/Berlin',weekday:'short',day:'numeric',month:'long'}).format(new Date(value+'T12:00:00Z')));option.value=value;day.append(option);}if([...day.options].some(o=>o.value===previous))day.value=previous;
  renderSlots();renderProposal(state.proposal);booked.replaceChildren();for(const booking of state.bookings||[]){const confirmed=booking.status==='confirmed'||(demo&&!booking.status),card=el('article',null,'frontdesk-booking');card.append(el('strong',format(booking.start)),el('p',`${booking.name} · ${booking.service||'Beratung'} · ${confirmed?'bestätigt':booking.status==='saving'?'Speicherung läuft – noch nicht bestätigt':'Buchungsstatus unklar – noch nicht bestätigt'}`));if(!confirmed&&booking.proposal_id){const check=el('button','Buchungsstatus prüfen','secondary');check.type='button';check.disabled=mutationBusy;check.addEventListener('click',()=>mutate('reconcile',{proposal_id:booking.proposal_id},'Buchungsstatus geprüft.'));card.append(check,el('p','Nur den vorhandenen Eintrag prüfen. Es wird kein neuer Termin angelegt.','field-hint'));}booked.append(card);}if(!booked.children.length)booked.append(el('p',demo?'Noch keine Demo-Termine bestätigt.':'Noch keine Buchungen über ATLAS.','quiet'));
  start.disabled=!!run||state.live?.enabled!==true;
 }
 function renderSlots(){slots.replaceChildren();for(const slot of (calendar?.available||[]).filter(s=>dayKey(s.start)===day.value)){const button=el('button',time(slot.start)+'–'+time(slot.end),'secondary');button.type='submit';button.value=slot.id;button.disabled=mutationBusy;slots.append(button);}if(!slots.children.length)slots.append(el('p','Für diesen Tag sind keine Zeiten frei.','quiet'));}
 function renderProposal(p){proposal.replaceChildren();proposal.hidden=!p;if(!p)return;proposal.append(el('span','BITTE PRÜFEN · NOCH NICHT GEBUCHT','section-kicker'),el('h3',format(p.start)),el('p',`${p.name} · ${p.service||'Beratung'} · bis ${time(p.end)}`));const controls=el('div',null,'frontdesk-actions'),confirm=el('button',calendar?.demo===false?'Termin im Firmenkalender bestätigen':'Demo-Termin bestätigen','primary'),cancel=el('button','Vorschlag verwerfen','secondary');confirm.type=cancel.type='button';confirm.disabled=cancel.disabled=mutationBusy||(p.status&&p.status!=='pending');confirm.addEventListener('click',()=>mutate('confirm',{proposal_id:p.id,confirmed:true},calendar?.demo===false?'Termin im Firmenkalender bestätigt.':'Demo-Termin bestätigt.'));cancel.addEventListener('click',()=>mutate('cancel',{proposal_id:p.id},'Vorschlag verworfen.'));controls.append(confirm,cancel);proposal.append(controls,el('p','Andere Wünsche? Sag es im Gespräch oder wähle eine andere freie Zeit. Ein neuer Vorschlag ersetzt den bisherigen.','field-hint'));}
 async function reload(){const seq=++loadSequence;const state=await api('state');if(seq===loadSequence)render(state);return state;}
 async function mutate(path,data,message){if(mutationBusy)return;mutationBusy=true;renderSlots();renderProposal(calendar?.proposal);try{const response=await api(path,data);if(response.state)render(response.state);else await reload();if(['confirm','reconcile'].includes(path)&&calendar?.demo===false){message=response.result?.status==='confirmed'?'Termin im Firmenkalender bestätigt.':'Buchung noch nicht bestätigt. Prüfe den Buchungsstatus; keinen zweiten Termin anlegen.';}announce(message);if(run?.ready&&!run.closing)send(run,{type:'session.instructions.append',delegation_id:null,content:message+' Der Nutzer hat dies in der Oberfläche ausgelöst. Frage den Backend-Kalender nach dem aktuellen Stand.'});}catch(error){announce(error.message);}finally{mutationBusy=false;if(calendar)render(calendar);}}
 form.addEventListener('submit',event=>{event.preventDefault();if(!form.reportValidity())return;const id=event.submitter?.value;if(id)mutate('propose',{slot_id:id,name:name.value.trim()},'Vorschlag vorbereitet. Bitte unten prüfen und bestätigen.');});
 day.addEventListener('change',renderSlots);refresh.addEventListener('click',()=>reload().then(()=>announce(calendar?.demo===false?'Firmenkalender aktualisiert.':'Demo-Kalender aktualisiert.')).catch(error=>announce(error.message)));
 function active(state){return run===state&&!state.cleaned;}
 function send(state,event){if(active(state)&&state.ready&&state.channel?.readyState==='open')state.channel.send(JSON.stringify(event));}
 function closeServer(state){if(!state.id||state.serverClosed)return;state.serverClosed=true;api('close',{session_id:state.id,client_closed:state.finalized===true},{keepalive:true}).catch(()=>{if(!run)announce('Gespräch lokal beendet. Server-Abschluss nicht bestätigt; die serverseitige Zeitbegrenzung bleibt aktiv.');});}
 function cleanup(state,message){if(state.cleaned)return;state.cleaned=true;clearTimeout(state.connectTimer);clearTimeout(state.durationTimer);clearTimeout(state.closeTimer);state.stream?.getTracks().forEach(t=>t.stop());state.channel?.close();state.peer?.close();closeServer(state);if(run===state){run=null;audio.pause();audio.srcObject=null;audio.hidden=true;stop.disabled=true;start.disabled=calendar?.live?.enabled!==true;if(message)announce(message);}}
 function finish(message='Gespräch beendet.'){
  const state=run;if(!state||state.closing)return;state.closing=true;stop.disabled=true;audio.pause();state.stream?.getTracks().forEach(t=>t.enabled=false);
  if(state.ready&&state.channel?.readyState==='open'){send(state,{type:'session.close'});announce('Gespräch wird beendet …');state.closeTimer=setTimeout(()=>cleanup(state,'Gespräch beendet; endgültige Nutzungsbestätigung fehlt.'),15000);}
  else cleanup(state,message);
 }
 async function processTool(state,item){
  if(!active(state)||state.closing)return;
  const supported=['check_availability','propose_appointment','cancel_proposal','list_bookings','end_conversation'];let result;
  try{if(!supported.includes(item.name))throw Error('Diese Aktion ist nicht freigegeben. Buchungen benötigen eine Bestätigung in der Oberfläche.');const args=JSON.parse(item.arguments);if(!args||Array.isArray(args)||typeof args!=='object')throw Error('Ungültige Terminanfrage.');const response=await api('tool',{session_id:state.id,name:item.name,arguments:args});result=response.result;if(!active(state)||state.closing)return;if(response.state)render(response.state);else await reload();}
  catch(error){result={error:error.message};}
  if(!active(state)||state.closing)return;send(state,{type:'response.item.create',item:{type:'function_call_output',call_id:item.call_id,output:JSON.stringify(result)}});send(state,{type:'response.create'});if(result?.finish===true)finish();
 }
 function onEvent(state,data){
  if(!active(state))return;let event;try{event=JSON.parse(data);}catch{return;}
  if(event.type==='session.closed'){state.finalized=true;cleanup(state,'Gespräch beendet.');return;}
  if(state.closing)return;
  if(event.type==='session.started'){state.ready=true;clearTimeout(state.connectTimer);announce('ATLAS hört zu. Du kannst jederzeit unterbrechen und deine Wünsche ändern.');send(state,{type:'session.instructions.append',delegation_id:null,content:calendar?.demo===false?'Begrüße den Nutzer kurz auf Deutsch und frage nach dem gewünschten Beratungstermin im Firmenkalender. Buchungen brauchen die ausdrückliche Bestätigung in der Oberfläche.':'Begrüße den Nutzer kurz auf Deutsch und frage nach dem gewünschten Demo-Beratungstermin.'});}
  else if(event.type==='session.input_transcript.delta')line('user',event.delta);
  else if(event.type==='session.output_transcript.delta')line('assistant',event.delta);
  else if(event.type==='error'){cleanup(state,'Die Online-Sprachverbindung meldet einen Fehler. API-Zugang und Modellfreigabe prüfen.');}
  else if(event.type==='response.event'){
   const nested=event.event||{};if(nested.type==='response.failed'){announce('Die Terminprüfung ist fehlgeschlagen. Bitte prüfe den Kalenderstatus in der Oberfläche.');return;}
   const item=nested.item;if(nested.type==='response.output_item.done'&&item?.type==='function_call'&&typeof item.call_id==='string'&&!state.calls.has(item.call_id)){
    state.calls.add(item.call_id);state.tools=state.tools.then(()=>processTool(state,item)).catch(()=>{if(active(state))announce('Terminprüfung unterbrochen. Bitte erneut versuchen.');});
   }
  }
 }
 async function waitICE(state){if(state.peer.iceGatheringState==='complete')return;await new Promise((resolve,reject)=>{const peer=state.peer;const timer=setTimeout(()=>{peer.removeEventListener('icegatheringstatechange',check);reject(Error('Verbindungsaufbau dauert zu lange. Bitte erneut starten.'));},10000);function check(){if(peer.iceGatheringState==='complete'){clearTimeout(timer);peer.removeEventListener('icegatheringstatechange',check);resolve();}}peer.addEventListener('icegatheringstatechange',check);check();});}
 start.addEventListener('click',async()=>{
  if(run||calendar?.live?.enabled!==true)return;
  if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia||!window.RTCPeerConnection){announce('Sprachgespräche benötigen HTTPS und einen Browser mit Mikrofonzugriff.');return;}
  window.dispatchEvent(new Event('atlas-frontdesk-start'));
  const state={ready:false,closing:false,cleaned:false,calls:new Set(),tools:Promise.resolve()};run=state;start.disabled=true;stop.disabled=false;transcript.replaceChildren();announce('Mikrofon freigeben und Verbindung aufbauen …');
  state.connectTimer=setTimeout(()=>cleanup(state,'Verbindungsaufbau abgebrochen. Bitte Mikrofonfreigabe und API-Zugang prüfen.'),45000);
  try{
   const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});if(!active(state)){stream.getTracks().forEach(t=>t.stop());return;}state.stream=stream;
   const peer=new RTCPeerConnection();state.peer=peer;for(const track of stream.getAudioTracks())peer.addTrack(track,stream);
   peer.addEventListener('track',event=>{if(!active(state)||state.closing)return;audio.srcObject=new MediaStream([event.track]);audio.hidden=false;audio.play().catch(()=>{if(active(state))announce('Bitte auf Wiedergabe am Audioplayer tippen, um ATLAS zu hören.');});});
   peer.addEventListener('connectionstatechange',()=>{if(active(state)&&['failed','closed'].includes(peer.connectionState))cleanup(state,'Sprachverbindung unterbrochen. Bitte erneut starten.');});
   state.channel=peer.createDataChannel('oai-events');state.channel.addEventListener('message',event=>onEvent(state,event.data));state.channel.addEventListener('close',()=>{if(active(state))cleanup(state,'Verbindung beendet; endgültige Nutzungsbestätigung fehlt.');});
   await peer.setLocalDescription(await peer.createOffer());await waitICE(state);if(!active(state))return;
   const response=await api('session',{sdp:peer.localDescription.sdp});state.id=response.session.id;if(!active(state)){closeServer(state);return;}
   await peer.setRemoteDescription({type:'answer',sdp:response.transport.sdp});if(!active(state))return;
   state.durationTimer=setTimeout(()=>finish(),Math.min(Number(calendar.live.max_seconds)||600,600)*1000);
  }catch(error){if(active(state))cleanup(state,({NotAllowedError:'Mikrofonzugriff abgelehnt. Bitte in den Browser-Einstellungen erlauben und erneut starten.',NotFoundError:'Kein Mikrofon gefunden.',NotReadableError:'Das Mikrofon ist gerade nicht verfügbar.'})[error.name]||error.message||'Sprachverbindung fehlgeschlagen.');}
 });
 stop.addEventListener('click',()=>finish());
 window.addEventListener('atlas-local-voice-start',()=>finish());
 window.addEventListener('pagehide',()=>{if(run){const state=run;if(state.ready)send(state,{type:'session.close'});cleanup(state);}});
 document.addEventListener('visibilitychange',()=>{if(document.hidden)finish();});
 document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{if(button.dataset.view!=='chat')finish();}));
 panel.addEventListener('toggle',()=>{if(!panel.open)finish();});
 reload().then(state=>announce(state.live?.enabled?(state.demo===false?'Bereit. Starte das Gespräch oder wähle einen Termin im Firmenkalender.':'Bereit. Starte das Gespräch oder wähle einen Demo-Termin.'):(state.live?.reason||'Online-Sprache noch nicht freigegeben.')+(state.demo===false?' '+(state.notice||''):' Der Demo-Kalender funktioniert ohne API.'))).catch(error=>announce(error.message));
})();
