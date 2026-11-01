const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
class Node{
 constructor(tag='div'){this.tagName=tag;this.children=[];this.value='';this.textContent='';this.hidden=false;this.dataset={};this.listeners={};this.attributes={};this.classList={toggle(){},add(){},remove(){}};this.lastElementChild={textContent:''};}
 append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;this.textContent='';}setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];}addEventListener(k,v){this.listeners[k]=v;}querySelector(){return new Node('button');}querySelectorAll(){return [];}reset(){}focus(){}scrollIntoView(){}get options(){return this.children;}
}
const source=fs.readFileSync('ftst_atlas/app.js','utf8'),html=fs.readFileSync('ftst_atlas/index.html','utf8');
for(const m of source.matchAll(/\$\('([^']+)'\)/g))assert(html.includes('id="'+m[1]+'"'),'Missing HTML ID '+m[1]);
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
const text=n=>[n.textContent,...n.children.map(text)].join(' ');
const find=(n,value)=>{if(n.textContent===value)return n;for(const c of n.children){const match=find(c,value);if(match)return match;}};
const calls=[],timers=[],windowListeners={};let jobs=[],trackStops=0,recordRequests=0,voiceEnabled=true,playCount=0,revokeCount=0;
class Recorder{static isTypeSupported(type){return type.startsWith('audio/webm');}constructor(){this.listeners={};this.state='inactive';Recorder.last=this;}addEventListener(k,fn){this.listeners[k]=fn;}start(){this.state='recording';}stop(){this.state='inactive';this.listeners.dataavailable({data:new Blob(['audio'],{type:'audio/webm;codecs=opus'})});this.listeners.stop();}}
const context=vm.createContext({document:{getElementById:get,querySelector:()=>new Node(),querySelectorAll:()=>[],createElement:tag=>{const n=new Node(tag);if(tag==='audio'){n.play=async()=>{playCount++;};n.pause=()=>{};}return n;},createTextNode:t=>Object.assign(new Node(),{textContent:t}),createDocumentFragment:()=>new Node()},window:{location:{pathname:'/',hash:''},confirm:()=>true,addEventListener(type,fn){windowListeners[type]=fn;}},navigator:{mediaDevices:{getUserMedia:async()=>{recordRequests++;return{getTracks:()=>[{stop(){trackStops++;}}]};}}},MediaRecorder:Recorder,Blob,AbortController,fetch:async(path,opts={})=>{const method=opts.method||'GET';calls.push({path,method,body:opts.body,headers:opts.headers});let data={};
 if(path==='api/status')data={csrf_token:'test-csrf',voice:{enabled:voiceEnabled}};
 else if(path==='api/tasks')data={tasks:[]};
 else if(path==='api/jobs'&&method==='POST')data={id:'chat1'};
 else if(path==='api/jobs/chat1')data={status:'completed',result:{reply:'Synthetische Antwort'}};
 else if(path==='api/jobs')data={jobs};
 else if(path==='api/workflows/catalog')data={workflows:[{id:'briefing',title:'Tagesüberblick',description:'Eigene Quellen prüfen',enabled:true},{id:'bookkeeping',title:'Monat vorbereiten',description:'Belege prüfen',enabled:true,requires_month:true}]};
 else if(path==='api/workflows'){jobs=[{id:'wf1',title:'Testablauf',created_at:'2026-10-29',status:'completed',steps:[{label:'Quellen lesen',status:'completed',detail:'<script>nur Text</script>'}],result:{workflow:'bookkeeping',reply:'Ergebnis',incomplete:true,artifact:{url:'api/workflows/wf1/download',filename:'export.zip'}}}];data=jobs[0];}
 else if(path==='api/voice/transcribe')data={text:'Geprüfter Testtext'};
 return{ok:true,status:200,json:async()=>data,blob:async()=>new Blob(['wav'],{type:'audio/wav'})};
},console,URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){revokeCount++;}},URLSearchParams,Date,Number,Object,Array,JSON,String,Promise,encodeURIComponent,setTimeout:(fn,delay)=>{timers.push(delay);if(delay===1500)setImmediate(fn);return 1;},clearTimeout(){}});
vm.runInContext(source.replace('loadStatus();loadTasks();','window.testLoadWorkflows=loadWorkflows;window.testLoadJobs=loadJobs;loadStatus();loadTasks();'),context);const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{await tick();assert.equal(recordRequests,0,'No microphone access on page load');assert.equal(get('voice-record').disabled,false);
 await context.window.testLoadWorkflows();
 get('workflow-kind').value='bookkeeping';get('workflow-kind').listeners.change();assert.equal(get('workflow-month-wrap').hidden,false);get('workflow-month').value='2026-10';
 await get('workflow-form').listeners.submit({preventDefault(){}});assert.match(text(get('job-list')),/Quellen lesen · Erledigt/);assert.match(text(get('job-list')),/Unvollständige Daten/);assert.equal(find(get('job-list'),'Export herunterladen').href,'api/workflows/wf1/download');
 jobs[0].result.artifact.url='https://example.com/leak';await context.window.testLoadJobs();assert.equal(find(get('job-list'),'Export herunterladen'),undefined);
 const workflowCall=calls.find(c=>c.path==='api/workflows');assert.deepEqual(JSON.parse(workflowCall.body),{workflow:'bookkeeping',month:'2026-10'});
 get('message').value='Entwurf';await get('voice-record').listeners.click();assert.equal(recordRequests,1);assert(timers.includes(60000),'Recording has a 60-second timer');assert.equal(get('send-button').disabled,true);await get('voice-record').listeners.click();await tick();assert(trackStops>0);assert.equal(get('message').value,'Entwurf\nGeprüfter Testtext');assert.equal(calls.filter(c=>c.path==='api/jobs'&&c.method==='POST').length,0,'Transcript never auto-submitted');
 const beforeHandoff=get('message').value;await get('voice-record').listeners.click();assert.equal(get('send-button').disabled,true);windowListeners['atlas-frontdesk-start']();await tick();assert.equal(get('send-button').disabled,false,'Front Desk switch releases composer');assert.equal(get('voice-record').disabled,false,'Front Desk switch releases local recorder');assert.equal(get('message').value,beforeHandoff,'Cancelled recorder cannot insert stale transcript');assert.equal(calls.filter(c=>c.path==='api/voice/transcribe').length,1,'Switch does not upload cancelled recording');
 await get('voice-record').listeners.click();await get('voice-cancel').listeners.click();await tick();assert.equal(calls.filter(c=>c.path==='api/voice/transcribe').length,1,'Discarded recording is not uploaded');
 get('voice-file').files=[new Blob(['file'],{type:'audio/wav'})];await get('voice-file').listeners.change();assert.equal(calls.filter(c=>c.path==='api/voice/transcribe').length,2);
 get('voice-file').files=[{type:'audio/wav',size:5242881}];await get('voice-file').listeners.change();assert.equal(calls.filter(c=>c.path==='api/voice/transcribe').length,2,'Oversize file rejected');
 get('message').value='Hallo';await get('chat-form').listeners.submit({preventDefault(){}});const read=find(get('messages'),'Vorlesen');assert(read);await read.listeners.click();assert.equal(playCount,1);await find(get('messages'),'Vorlesen stoppen').listeners.click();assert.equal(revokeCount,1);
 assert(calls.filter(c=>c.method==='POST').every(c=>c.headers['X-Atlas-CSRF']==='test-csrf'));
 voiceEnabled=false;await get('refresh-status').listeners.click();assert.equal(get('voice-record').disabled,true);assert.equal(get('voice-file').disabled,true);voiceEnabled=true;context.MediaRecorder=undefined;await get('refresh-status').listeners.click();assert.equal(get('voice-record').disabled,true);assert.equal(get('voice-file').disabled,false,'File fallback available without MediaRecorder');
 console.log('Workflow/voice UI checks passed: catalog, month, steps, safe artifact, incomplete warning, explicit mic, track cleanup, review-only transcript, discard, file limits, local playback cleanup, CSRF.');
})().catch(e=>{console.error(e);process.exit(1);});
