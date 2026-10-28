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
let memory={id:1,text:'Synthetisches Projekt November',source:'Testquelle',tags:['Projekt'],revision:1,created_at:'2026-10-29T08:00:00Z',updated_at:'2026-10-29T08:00:00Z'},revisions=[{...memory}],tasks=[],conflict=false;const calls=[];
const context=vm.createContext({document:{getElementById:get,querySelector:()=>new Node(),querySelectorAll:()=>[],createElement:tag=>new Node(tag),createTextNode:t=>Object.assign(new Node(),{textContent:t}),createDocumentFragment:()=>new Node()},window:{location:{pathname:'/',hash:''},confirm:()=>true},fetch:async(path,opts={})=>{const body=opts.body?JSON.parse(opts.body):{},method=opts.method||'GET';calls.push({path,method,body,headers:opts.headers});let data={},status=200;
 if(path==='api/status')data={csrf_token:'test-csrf'};
 else if(path==='api/profile')data={text:''};
 else if(path==='api/jobs')data={jobs:[]};
 else if(path==='api/memories/1/revisions')data={revisions};
 else if(path==='api/memories/1'&&method==='PATCH'){if(conflict){status=409;data={error:'Konflikt'};}else{assert.equal(body.revision,memory.revision);memory={...memory,...body,revision:memory.revision+1};revisions.unshift({...memory});data={memory};}}
 else if(path.startsWith('api/memories'))data={memories:path.includes('unbekannt')?[]:[memory]};
 else if(path==='api/tasks'&&method==='POST'){tasks=[{id:1,...body,done:false}];data={task:tasks[0]};}
 else if(path==='api/tasks')data={tasks};
 return {ok:status===200,status,json:async()=>data};
},console,URL,URLSearchParams,Date,Number,Object,Array,JSON,String,Promise,encodeURIComponent,setTimeout:()=>1,clearTimeout(){}});
vm.runInContext(source,context);
const tick=()=>new Promise(r=>setImmediate(r));const submit=async id=>{await get(id).listeners.submit({preventDefault(){},currentTarget:get(id)});await tick();};
(async()=>{await tick();await submit('memory-search-form');assert.match(text(get('memory-list')),/Testquelle/);
 get('memory-search').value='unbekannt';await submit('memory-search-form');assert.match(text(get('memory-list')),/Keine passenden/);
 await get('memory-search-reset').listeners.click();await tick();
 await find(get('memory-list'),'Korrigieren').listeners.click();assert.equal(get('memory-text').value,memory.text);
 get('memory-text').value='Korrigiert <img src=x onerror=alert(1)>';get('memory-source').value='Prüfung';get('memory-tags').value='Projekt, Dezember';await submit('memory-form');assert.equal(memory.revision,2);assert.deepEqual(memory.tags,['Projekt','Dezember']);assert.match(text(get('memory-list')),/<img src=x/);assert.equal(get('memory-list').children.some(n=>n.tagName==='img'),false);
 const details=get('memory-list').children[0].children.find(n=>n.tagName==='details');details.open=true;await details.listeners.toggle();assert.match(text(details),/Synthetisches Projekt November/);
 await find(get('memory-list'),'Korrigieren').listeners.click();conflict=true;get('memory-text').value='Nicht verlieren';await submit('memory-form');assert.equal(get('memory-text').value,'Nicht verlieren');assert.equal(get('notice').textContent,'Konflikt');conflict=false;
 await get('memory-cancel').listeners.click();await find(get('memory-list'),'Aufgabe dazu').listeners.click();get('task-title').value='Prüfen';await submit('task-form');assert.deepEqual(tasks[0].knowledge_ids,[1]);assert.equal(get('task-knowledge-selection').hidden,true);
 const linked=get('task-list').children[0].children.find(n=>n.tagName==='details');linked.open=true;await linked.listeners.toggle();assert.match(text(linked),/Korrigiert/);
 const writes=calls.filter(c=>c.method!=='GET');assert(writes.every(c=>c.headers['X-Atlas-CSRF']==='test-csrf'));assert.equal(writes.length,3);
 console.log('Knowledge UI checks passed: search, tags, correction/history, conflict retention, task linkage, provenance, CSRF, HTML ID wiring.');
})().catch(e=>{console.error(e);process.exit(1);});
