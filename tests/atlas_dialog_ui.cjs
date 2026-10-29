'use strict';
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
class Node{
 constructor(tag='div'){this.tagName=tag;this.children=[];this.value='';this.textContent='';this.hidden=false;this.dataset={};this.listeners={};this.attributes={};this.classList={toggle(){},add(){},remove(){}};this.lastElementChild={textContent:''};}
 append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];}addEventListener(k,v){this.listeners[k]=v;}querySelector(){return new Node('button');}querySelectorAll(){return [];}reset(){}focus(){}scrollIntoView(){}get options(){return this.children;}
}
const source=fs.readFileSync('ftst_atlas/app.js','utf8'),html=fs.readFileSync('ftst_atlas/index.html','utf8');
for(const m of source.matchAll(/\$\('([^']+)'\)/g))assert(html.includes('id="'+m[1]+'"'),'Missing HTML ID '+m[1]);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function flush(){for(let n=0;n<8;n++)await tick();}
function setup(){
 const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
 const calls=[],timers=new Map(),audios=[],streams=[],events={};let timerId=0;
 const state={level:0,permissions:0,transcript:'Aufgabe anlegen: Testaufgabe',playBlocked:false,pendingPermission:null,pendingTranscription:null,pendingTurn:null,jobStatus:'completed',voiceEnabled:true};
 const stream=()=>{const s={stopped:false,getTracks:()=>[{stop(){s.stopped=true;}}]};streams.push(s);return s;};
 class Recorder{static isTypeSupported(type){return type.startsWith('audio/webm');}constructor(){this.listeners={};this.state='inactive';Recorder.last=this;}addEventListener(k,v){this.listeners[k]=v;}start(){this.state='recording';}stop(){this.state='inactive';this.listeners.dataavailable({data:new Blob(['audio'],{type:'audio/webm;codecs=opus'})});this.listeners.stop();}}
 class AudioContext{constructor(){this.state='running';}async resume(){}async close(){this.state='closed';}createAnalyser(){return{fftSize:2048,getFloatTimeDomainData(samples){samples.fill(state.level);}};}createMediaStreamSource(){return{connect(){},disconnect(){}};}}
 const document={getElementById:get,querySelector:()=>new Node(),querySelectorAll:()=>[],createElement:tag=>{const n=new Node(tag);if(tag==='audio'){audios.push(n);n.play=async()=>{assert(streams.every(s=>s.stopped),'Microphone must be stopped before playback');if(state.playBlocked)throw Object.assign(new Error('Blocked'),{name:'NotAllowedError'});};n.pause=()=>{};}return n;},createTextNode:t=>Object.assign(new Node(),{textContent:t}),createDocumentFragment:()=>new Node(),addEventListener:(event,callback)=>events[event]=callback};
 const window={location:{pathname:'/',hash:''},confirm:()=>true,addEventListener:(event,callback)=>events[event]=callback,AudioContext};
 const context=vm.createContext({document,window,navigator:{mediaDevices:{getUserMedia:async()=>{state.permissions++;if(state.pendingPermission)return state.pendingPermission;return stream();}}},MediaRecorder:Recorder,Blob,Float32Array,Uint8Array,AbortController,crypto:require('node:crypto').webcrypto,fetch:async(path,options={})=>{
  calls.push({path,options});let data={};
  if(path==='api/status')data={csrf_token:'csrf',voice:{enabled:state.voiceEnabled}};
  else if(path==='api/tasks')data={tasks:[]};
  else if(path==='api/voice/transcribe'){assert(streams.every(s=>s.stopped),'Mic must be stopped before transcription');if(state.pendingTranscription)await state.pendingTranscription;data={text:state.transcript};}
  else if(path==='api/voice/turn'){if(state.pendingTurn)await state.pendingTurn;data={id:'dialog-job'};}
  else if(path==='api/jobs/dialog-job')data={status:state.jobStatus,result:{reply:'Aufgabe gespeichert.',action:'task_created'}};
  return{ok:true,status:200,json:async()=>data,blob:async()=>new Blob(['wav'],{type:'audio/wav'})};
 },URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},URLSearchParams,Date,Number,Object,Array,JSON,String,Promise,encodeURIComponent,setTimeout:(fn,delay)=>{const id=++timerId;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id),console});
 vm.runInContext(source,context);
 const run=async delay=>{const found=[...timers.entries()].find(([,v])=>v.delay===delay);assert(found,'No pending '+delay+'ms timer');timers.delete(found[0]);found[1].fn();await flush();};
 const utterance=async()=>{state.level=.08;for(let n=0;n<5;n++)await run(100);state.level=0;for(let n=0;n<20;n++)await run(100);};
 return{state,get,calls,timers,events,document,streams,audios,Recorder,stream,run,utterance};
}
(async()=>{
 let h=setup();await flush();assert.equal(h.state.permissions,0);assert.equal(h.get('dialogue-start').disabled,false);
 h.get('message').value='Ungesendeter Entwurf';await h.get('dialogue-start').listeners.click();assert.equal(h.state.permissions,0,'Never discard an existing draft');h.get('message').value='';
 await h.get('dialogue-start').listeners.click();assert.equal(h.state.permissions,1);assert.equal(h.get('voice-record').disabled,true);assert.equal(h.get('message').disabled,true);assert.equal(h.get('dialogue-stop').hidden,false);
 await h.utterance();assert.equal(h.calls.filter(c=>c.path==='api/voice/turn').length,1);const body=JSON.parse(h.calls.find(c=>c.path==='api/voice/turn').options.body);assert.equal(body.message,'Aufgabe anlegen: Testaufgabe');assert.match(body.request_id,/^[a-f0-9-]{36}$/);assert.equal(h.state.permissions,1,'No rearm during job');
 await h.run(1500);assert.equal(h.audios.length,1);assert.equal(h.state.permissions,1,'No rearm during speech');assert.match(h.get('dialogue-status').textContent,/ATLAS spricht/);
 const oldAudio=h.audios[0];oldAudio.listeners.ended();await flush();assert.equal(h.state.permissions,2,'Rearm only after playback ended');oldAudio.listeners.ended();await flush();assert.equal(h.state.permissions,2,'Ignore duplicate stale audio event');
 h.get('dialogue-stop').listeners.click();await flush();assert(h.streams.every(s=>s.stopped));assert.equal(h.get('dialogue-stop').hidden,true);assert.equal(h.get('voice-record').disabled,false);assert.equal(h.get('message').disabled,false);
 oldAudio.listeners.ended();await flush();assert.equal(h.state.permissions,2,'Stop prevents stale rearm');
 h=setup();await flush();let resolvePermission;h.state.pendingPermission=new Promise(r=>resolvePermission=r);const start=h.get('dialogue-start').listeners.click();await flush();h.get('dialogue-stop').listeners.click();const lateStream=h.stream();resolvePermission(lateStream);await start;assert(lateStream.stopped,'Stop during permission request closes late stream');assert.equal(h.calls.filter(c=>c.path==='api/voice/transcribe').length,0);
 h=setup();await flush();await h.get('dialogue-start').listeners.click();for(let n=0;n<150;n++)await h.run(100);assert.equal(h.get('dialogue-stop').hidden,true);assert.equal(h.calls.filter(c=>c.path==='api/voice/transcribe').length,0,'No-speech input must not reach Whisper');
 h=setup();await flush();await h.get('dialogue-start').listeners.click();let resolveTranscription;h.state.pendingTranscription=new Promise(r=>resolveTranscription=r);await h.utterance();h.get('dialogue-stop').listeners.click();resolveTranscription();await flush();assert.equal(h.calls.filter(c=>c.path==='api/voice/turn').length,0,'Cancelled transcription cannot dispatch a command');
 h=setup();await flush();h.state.playBlocked=true;await h.get('dialogue-start').listeners.click();await h.utterance();await h.run(1500);assert.equal(h.get('dialogue-stop').hidden,true);assert.match(h.get('dialogue-status').textContent,/Vorlesen/);assert.equal(h.state.permissions,1);
 h=setup();await flush();await h.get('dialogue-start').listeners.click();await h.utterance();h.get('dialogue-stop').listeners.click();await h.run(1500);assert.equal(h.audios.length,0);assert.match(h.get('dialogue-status').textContent,/Aufträge können weiterlaufen/);
 h=setup();await flush();let resolveTurn;h.state.pendingTurn=new Promise(r=>resolveTurn=r);await h.get('dialogue-start').listeners.click();await h.utterance();h.get('dialogue-stop').listeners.click();resolveTurn();await flush();assert.equal(h.calls.filter(c=>c.path==='api/jobs/dialog-job').length,0,'Late accepted job cannot restart polling or playback');assert.equal(h.audios.length,0);
 h=setup();await flush();h.state.transcript='Gespräch beenden';await h.get('dialogue-start').listeners.click();await h.utterance();assert.equal(h.calls.filter(c=>c.path==='api/voice/turn').length,0);assert.equal(h.get('dialogue-stop').hidden,true);
 h=setup();await flush();await h.get('dialogue-start').listeners.click();await h.run(600000);assert.equal(h.get('dialogue-stop').hidden,true);assert(h.streams.every(s=>s.stopped));
 h=setup();await flush();await h.get('dialogue-start').listeners.click();h.document.hidden=true;h.events.visibilitychange();assert(h.streams.every(s=>s.stopped));assert.equal(h.get('dialogue-stop').hidden,true);
 h=setup();await flush();await h.get('dialogue-start').listeners.click();h.events.pagehide();assert(h.streams.every(s=>s.stopped));assert.equal(h.get('dialogue-stop').hidden,true);
 h=setup();await flush();await h.get('dialogue-start').listeners.click();h.state.voiceEnabled=false;await h.get('refresh-status').listeners.click();assert(h.streams.every(s=>s.stopped));assert.equal(h.get('dialogue-start').disabled,true);
 console.log('Dialogue UI checks passed: explicit start, draft preservation, silence detection, half duplex, UUID dispatch, deferred rearm, cancellation, stale events, no speech, autoplay fallback, spoken stop, session timeout, visibility/page cleanup, permission revocation.');
})().catch(error=>{console.error(error);process.exit(1);});
