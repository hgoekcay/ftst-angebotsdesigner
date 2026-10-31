'use strict';
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
class Node{
 constructor(tag='div'){this.tagName=tag;this.children=[];this.value='';this.textContent='';this.hidden=false;this.open=false;this.dataset={};this.listeners={};this.attributes={};this.classList={toggle(){},add(){},remove(){}};this.lastElementChild={textContent:''};}
 append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];}addEventListener(k,v){this.listeners[k]=v;}querySelector(){return new Node('button');}querySelectorAll(){return [];}reset(){}focus(){}scrollIntoView(){}showModal(){this.open=true;}close(){this.open=false;}
}
const source=fs.readFileSync('ftst_atlas/app.js','utf8'),html=fs.readFileSync('ftst_atlas/index.html','utf8');
for(const m of source.matchAll(/\$\('([^']+)'\)/g))assert(html.includes('id="'+m[1]+'"'),'Missing HTML ID '+m[1]);
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
const text=n=>[n.textContent,...n.children.map(text)].join(' ');
const find=(n,value)=>n.textContent===value?n:n.children.map(c=>find(c,value)).find(Boolean);
const calls=[];let waitExtract=null;
const record={id:'doc1',mime:'application/pdf',filename:'synthetic.pdf',fields:{supplier:'Manual value',gross:'119.00',payment_status:'paid'},reviewed:true,audit:[]};
const context=vm.createContext({document:{getElementById:get,querySelector:()=>new Node(),querySelectorAll:()=>[],createElement:tag=>new Node(tag),createTextNode:t=>Object.assign(new Node(),{textContent:t}),createDocumentFragment:()=>new Node()},window:{location:{pathname:'/',hash:''},addEventListener(){}},navigator:{},AbortController,fetch:async(path,opts={})=>{
 calls.push({path,...opts});let data={};
 if(path==='api/status')data={csrf_token:'test-csrf'};
 else if(path==='api/tasks')data={tasks:[]};
 else if(path==='api/bookkeeping/doc1')data=record;
 else if(path==='api/bookkeeping/doc2')data={...record,id:'doc2',mime:'image/png'};
 else if(path==='api/bookkeeping/doc1/extract'){if(waitExtract)await waitExtract;data={suggestions:{supplier:'<script>candidate only</script>'},notes:[],saved:false};}
 return{ok:true,status:200,json:async()=>data};
},URLSearchParams,Date,Number,Object,Array,JSON,String,Promise,encodeURIComponent,setTimeout:()=>1,clearTimeout(){},console});
vm.runInContext(source.replace('loadStatus();loadTasks();','window.openRecordForTest=openBookkeepingRecord;loadStatus();loadTasks();'),context);
(async()=>{
 await context.window.openRecordForTest('doc1');
 assert.equal(get('bookkeeping-extraction-controls').hidden,false);
 get('review-supplier').value='Unsaved human edit';
 await get('bookkeeping-reextract').listeners.click();
 assert.equal(get('review-supplier').value,'Unsaved human edit');
 assert.equal(get('review-reviewed').checked,true,'Extraction itself must not change review state');
 assert.equal(get('review-payment').value,'paid');
 assert(text(get('bookkeeping-suggestions')).includes('<script>candidate only</script>'),'Candidate rendered as text');
 assert.equal(calls.filter(c=>c.method==='PATCH').length,0);
 const call=calls.find(c=>c.path.endsWith('/extract'));assert.equal(call.method,'POST');assert.equal(call.headers['X-Atlas-CSRF'],'test-csrf');
 find(get('bookkeeping-suggestions'),'Ins Prüfformular übernehmen').listeners.click();
 assert.equal(get('review-supplier').value,'<script>candidate only</script>');
 assert.equal(get('review-reviewed').checked,false,'Adopting a proposal requires fresh review');
 assert.equal(get('review-payment').value,'paid');
 assert.equal(calls.filter(c=>c.method==='PATCH').length,0,'Adoption changes only the local form');
 assert(text(get('bookkeeping-review-message')).includes('noch nicht gespeichert'));
 let release;waitExtract=new Promise(resolve=>release=resolve);
 const pending=get('bookkeeping-reextract').listeners.click();
 await context.window.openRecordForTest('doc2');
 assert.equal(get('bookkeeping-extraction-controls').hidden,true);
 release();await pending;
 assert.equal(get('bookkeeping-suggestions').children.length,0,'Late extraction must not populate another record');
 console.log('Bookkeeping extraction UI passed: explicit CSRF POST, no silent overwrite/save, safe text, fresh review on adoption, stale response isolation.');
})().catch(error=>{console.error(error);process.exit(1);});
