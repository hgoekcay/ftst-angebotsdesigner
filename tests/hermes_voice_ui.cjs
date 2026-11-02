'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ftst_hermes/client.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const natural = {name:'Deutsch Natürlich', lang:'de-DE', voiceURI:'natural', localService:false};
const compact = {name:'Deutsch Kompakt', lang:'de-DE', voiceURI:'compact', localService:true};

function app(store = new Map()) {
  const nodes = {}, sessions = [], spoken = [];
  function node(id) {
    return nodes[id] ||= {hidden:true, value:'', textContent:'', append(){}, add(){}, replaceChildren(){}};
  }
  let voices = [], changed;
  class Recognition { constructor(){ sessions.push(this); } start(){} abort(){} }
  const synth = {getVoices:()=>voices, addEventListener:(_,fn)=>{changed=fn;}, speak:u=>spoken.push(u), cancel(){}};
  let calls = 0;
  vm.runInNewContext(source, {
    document:{getElementById:node,querySelector:()=>node('form'),createElement:()=>({}),addEventListener(){}},
    window:{speechSynthesis:synth,SpeechRecognition:Recognition,addEventListener(){}},
    speechSynthesis:synth, SpeechSynthesisUtterance:class { constructor(text){this.text=text;} },
    Option:class {}, localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},
    setTimeout:()=>1, clearTimeout(){},
    fetch: async path=>({ok:true,json:async()=>path==='state'?{csrf:'test'}:(calls++,{reply:'Aufgabe gespeichert.'})})
  });
  return {node,spoken,sessions,setVoices(list){voices=list;changed();},calls:()=>calls};
}
test('German voice, device persistence, missing voice fallback and late discovery', async()=>{
  const store = new Map();
  const ui=app(store); await tick();
  ui.node('previewVoice').onclick();
  assert.equal(ui.spoken.at(-1).lang,'de-DE');
  ui.spoken.at(-1).onend();
  ui.setVoices([compact,natural,{...natural,lang:'en-US'}]);
  ui.node('previewVoice').onclick();
  assert.equal(ui.spoken.at(-1).voice,natural);
  assert.match(ui.node('voiceInfo').textContent,/Sprachanbieter/);
  ui.node('voiceSelect').value=JSON.stringify(['compact',compact.name,compact.lang]);
  ui.node('voiceSelect').onchange();
  assert.equal(ui.calls(),0);
  const reopened=app(store); await tick();
  reopened.setVoices([natural]);
  assert.match(reopened.node('voiceInfo').textContent,/Natürlich/);
  reopened.setVoices([natural,compact]);
  reopened.node('previewVoice').onclick();
  assert.equal(reopened.spoken.at(-1).voice,compact);
  assert.match(reopened.node('voiceInfo').textContent,/Gerät/);
});
test('preview cannot arm microphone or interrupt a conversation; chosen voice rearms once', async()=>{
  const ui=app();await tick();ui.setVoices([natural]);
  ui.node('previewVoice').onclick();assert.equal(ui.sessions.length,0);
  ui.node('voice').onclick();assert.equal(ui.sessions.length,1);
  ui.node('previewVoice').onclick();assert.equal(ui.spoken.length,1);
  ui.sessions[0].onresult({results:[[{transcript:'Welche Aufgaben habe ich?'}]]});
  ui.sessions[0].onend();await tick();
  assert.equal(ui.spoken[1].voice,natural);
  assert.equal(ui.sessions.length,1);
  ui.spoken[1].onend();assert.equal(ui.sessions.length,2);
  ui.node('voice').onclick();assert.equal(ui.node('previewVoice').disabled,false);
});
