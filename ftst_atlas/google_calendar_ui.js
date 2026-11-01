/* Direct Google Calendar setup; secrets never enter this interface. */
'use strict';
(() => {
 const host=document.getElementById('view-system');
 if(!host||/\/submit\/?$/.test(location.pathname))return;
 const el=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n;};
 const card=el('article');card.className='card';card.id='google-calendar-setup';
 const heading=el('h2','Google Kalender direkt verbinden'),status=el('p','Verbindung wird geprüft …');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
 const details=el('p'),start=el('button','Mit Google verbinden'),finish=el('button','Verbindung übernehmen'),refresh=el('button','Status aktualisieren'),disconnect=el('button','Google-Verbindung in ATLAS entfernen');
 const auth=el('a','Google-Anmeldung öffnen');auth.target='_blank';auth.rel='noopener noreferrer';auth.hidden=true;auth.className='btn';
 const label=el('label','Firmenkalender auswählen'),select=el('select');select.id='atlas-google-calendar';label.htmlFor=select.id;const save=el('button','Diesen Kalender verwenden');
 for(const button of [start,finish,refresh,disconnect,save]){button.type='button';button.className='secondary';}
 card.append(heading,status,details,start,auth,finish,refresh,label,select,save,disconnect,el('p','Die Google-Freigabe erlaubt Kalenderzugriff. ATLAS verwendet nur den ausdrücklich ausgewählten Kalender. Buchungen benötigen weiterhin deine Bestätigung. Zugangsdaten bleiben auf dem Server.'));
 host.append(card);
 let csrf='',busy=false,current=null;
 async function api(path,data){
  if(data!==undefined&&!csrf){const r=await fetch('api/status',{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw Error('ATLAS-Sitzung nicht verfügbar.');csrf=(await r.json()).csrf_token;if(!csrf)throw Error('ATLAS-Sitzung nicht bereit.');}
  const r=await fetch('api/google/'+path,{method:data===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json',...(csrf?{'X-Atlas-CSRF':csrf}:{})},...(data===undefined?{}:{body:JSON.stringify(data)})});
  const result=await r.json();if(!r.ok)throw Error(result.error||'Google-Verbindung konnte nicht geprüft werden.');return result;
 }
 function render(value){current=value;const oauth=value.oauth||{};status.textContent=oauth.connected?'Google-Zugang gespeichert. '+(value.calendar?.enabled?'Firmenkalender ausgewählt.':'Bitte Firmenkalender auswählen.'):(oauth.reason||'Noch nicht verbunden.');details.textContent=oauth.configured?'Rückleitungsadresse: '+oauth.redirect_uri:'In der Add-on-Konfiguration Google als Kalenderanbieter wählen und Client-ID, Client-Geheimnis, Besitzer-ID sowie HTTPS-Rückleitungsadresse eintragen.';
  start.disabled=busy||!oauth.configured;finish.hidden=!oauth.pending;finish.disabled=busy||!oauth.pending;disconnect.hidden=!oauth.connected;disconnect.disabled=busy;refresh.disabled=busy;label.hidden=select.hidden=save.hidden=!oauth.connected;save.disabled=busy||!select.value;
 }
 async function loadCalendars(){const value=await api('calendars');select.replaceChildren();const empty=el('option','Bitte bewusst auswählen');empty.value='';select.append(empty);for(const item of value.calendars||[]){const option=el('option',item.name||item.summary||item.id);option.value=item.id;select.append(option);}select.value=value.selected_id||'';}
 async function reload(){const state=await api('status');render(state);if(state.oauth?.connected)await loadCalendars();render(state);}
 async function action(fn){if(busy)return;busy=true;if(current)render(current);try{await fn();}catch(e){status.textContent=e.message;}finally{busy=false;if(current){start.disabled=!current.oauth?.configured;finish.disabled=!current.oauth?.pending;disconnect.disabled=false;refresh.disabled=false;save.disabled=!select.value;}}}
 start.addEventListener('click',()=>action(async()=>{auth.hidden=true;auth.removeAttribute('href');const result=await api('begin',{});const url=new URL(result.authorization_url);if(url.origin!=='https://accounts.google.com'||url.pathname!=='/o/oauth2/v2/auth')throw Error('Google-Anmeldeadresse ungültig.');auth.href=url.href;auth.hidden=false;status.textContent='Öffne die Google-Anmeldung. Danach hier den Status aktualisieren und die Verbindung übernehmen.';}));
 finish.addEventListener('click',()=>action(async()=>{await api('finish',{});auth.hidden=true;auth.removeAttribute('href');await reload();}));
 save.addEventListener('click',()=>action(async()=>{await api('select',{calendar_id:select.value});await reload();}));
 disconnect.addEventListener('click',()=>action(async()=>{await api('disconnect',{});auth.hidden=true;auth.removeAttribute('href');select.replaceChildren();await reload();}));
 refresh.addEventListener('click',()=>action(reload));select.addEventListener('change',()=>{save.disabled=busy||!select.value;});
 reload().catch(e=>{status.textContent=e.message;start.disabled=finish.disabled=save.disabled=true;});
})();
