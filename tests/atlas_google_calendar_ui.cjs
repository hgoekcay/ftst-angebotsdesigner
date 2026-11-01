'use strict';
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
class Node{
 constructor(tag){this.tagName=tag;this.children=[];this.listeners={};this.dataset={};this._text='';this.value='';this.hidden=false;this.disabled=false;this.attributes={};}
 append(...nodes){for(const node of nodes){node.parentNode=this;this.children.push(node);}}
 after(node){const p=this.parentNode;p.children.splice(p.children.indexOf(this)+1,0,node);node.parentNode=p;}
 replaceChildren(...nodes){this.children=[];this.append(...nodes);}
 removeAttribute(k){delete this[k];delete this.attributes[k];}
 remove(){const p=this.parentNode;p.children.splice(p.children.indexOf(this),1);}
 setAttribute(k,v){this.attributes[k]=v;}
 addEventListener(k,v){(this.listeners[k]??=[]).push(v);}
 removeEventListener(k,v){this.listeners[k]=(this.listeners[k]||[]).filter(x=>x!==v);}
 emit(type,extra={}){return Promise.all((this.listeners[type]||[]).map(fn=>fn({type,target:this,...extra})));}
 get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}set textContent(v){this._text=v;this.children=[];}
 get lastElementChild(){return this.children.at(-1);}get firstElementChild(){return this.children[0];}get options(){return this.children;}
 reportValidity(){return true;}play(){return Promise.resolve();}pause(){}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));async function flush(){for(let n=0;n<12;n++)await tick();}
function setup(state={configured:true,connected:false,pending:false}){
 const nodes=[],host=new Node('section');nodes.push(host);host.id='view-system';const requests=[];
 const document={getElementById:id=>nodes.find(n=>n.id===id),createElement:tag=>{const n=new Node(tag);nodes.push(n);return n;}};
 let authURL='https://accounts.google.com/o/oauth2/v2/auth?state=test';
 const fetch=async(url,options={})=>{requests.push({url,options});let result={};if(url==='api/status')result={csrf_token:'csrf'};else if(url.endsWith('/status'))result={oauth:{...state},calendar:{enabled:false}};else if(url.endsWith('/begin'))result={authorization_url:authURL};else if(url.endsWith('/finish')){state.pending=false;state.connected=true;}else if(url.endsWith('/calendars'))result={calendars:[{id:'company',name:'<script>calendar</script>'}],selected_id:''};else if(url.endsWith('/disconnect'))state.connected=false;return {ok:true,json:async()=>result};};
 vm.runInNewContext(fs.readFileSync('ftst_atlas/google_calendar_ui.js','utf8'),{document,location:{pathname:'/'},fetch,URL,Error});
 return{nodes,requests,state,setURL:value=>authURL=value,find:text=>nodes.find(n=>n.tagName==='button'&&n.textContent===text)};
}
(async()=>{
 let count=0;
 {const s=setup({configured:false});await flush();assert(s.find('Mit Google verbinden').disabled);assert(!s.requests.some(r=>r.options.method==='POST'));count++;}
 {const s=setup();await flush();await s.find('Mit Google verbinden').emit('click');await flush();const r=s.requests.find(r=>r.url.endsWith('/begin'));assert.equal(r.options.headers['X-Atlas-CSRF'],'csrf');assert.equal(s.nodes.find(n=>n.tagName==='a').hidden,false);assert(!s.requests.some(r=>r.url.endsWith('/finish')));count++;}
 {const s=setup();await flush();s.setURL('https://evil.invalid/oauth');await s.find('Mit Google verbinden').emit('click');await flush();assert(s.nodes.find(n=>n.tagName==='a').hidden);assert(s.nodes.some(n=>n.textContent.includes('Anmeldeadresse ungültig')));count++;}
 {const s=setup({configured:true,pending:true,connected:false});await flush();assert(!s.find('Verbindung übernehmen').hidden);await s.find('Verbindung übernehmen').emit('click');await flush();assert(s.state.connected);assert(s.find('Verbindung übernehmen').hidden);assert(s.nodes.some(n=>n.tagName==='option'&&n.textContent==='<script>calendar</script>'));assert(s.find('Diesen Kalender verwenden').disabled);assert(!s.requests.some(r=>r.url.endsWith('/select')));count++;}
 console.log(`Google setup: ${count} consent/CSRF/UI checks passed`);
})().catch(e=>{console.error(e);process.exitCode=1;});
