const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync(require('node:path').join(__dirname, '../ftst_angebotsdesigner/static/material-upload.js'), 'utf8');
const endpoint = '/api/hassio_ingress/test-session/material-upload';
const storageKey = 'ftst-photo-batch:' + endpoint;

function element(tag = 'div') {
  return {
    tag, children: [], handlers: {}, dataset: {}, style: {}, textContent: '', value: '',
    append(...children) { this.children.push(...children); },
    prepend(...children) { this.children.unshift(...children); },
    replaceChildren(...children) { this.children = children; },
    setAttribute(name, value) { this[name] = value; },
    addEventListener(name, handler) { this.handlers[name] = handler; },
    async emit(name) { return this.handlers[name]?.({preventDefault() {}, target: this}); },
  };
}

function response(value, status = 200) {
  return {status, ok: status >= 200 && status < 300, headers: {get: () => 'application/json'}, json: async () => value};
}

function harness({handle, stored = new Map()} = {}) {
  const input = element('input'), start = element('button'), commit = element('button');
  const form = element('form'), list = element(), message = element();
  const requests = [];
  let nextId = 0;
  form.dataset = {categories: JSON.stringify(['Videoüberwachung', 'Alarmanlage']), endpoint, library: '/materials'};
  form.querySelector = selector => selector === 'input[type=file]' ? input : start;
  const ids = {'photo-batch': form, 'photo-review': list, 'photo-progress': message, 'photo-commit': commit};
  vm.runInNewContext(script, {
    document: {getElementById: id => ids[id], createElement: element},
    Option: function Option(text, value) { return Object.assign(element('option'), {textContent: text, value}); },
    sessionStorage: {getItem: key => stored.get(key) || null, setItem: (key, value) => stored.set(key, value), removeItem: key => stored.delete(key)},
    crypto: {randomUUID: () => (++nextId).toString(16).padStart(32, '0')},
    URL: {createObjectURL: () => 'blob:preview-' + (++nextId), revokeObjectURL() {}},
    fetch: async (url, options = {}) => { requests.push({url, options}); return handle(url, options, stored); },
    File, FormData, AbortController,
    setTimeout: (callback, milliseconds) => { if (milliseconds < 60000) queueMicrotask(callback); return 1; },
    clearTimeout() {},
    window: {addEventListener() {}},
  });
  return {
    form, input, start, commit, list, message, requests, stored,
    async choose(names) { input.files = names.map(name => new File(['photo-content'], name, {type: 'image/jpeg', lastModified: 1})); await input.emit('change'); },
    async upload() { await form.emit('submit'); await flush(); },
    async save() { await commit.emit('click'); await flush(); },
  };
}

async function flush() {
  // Handlers intentionally launch asynchronous processing without returning it.
  for (let i = 0; i < 30; i++) await new Promise(resolve => setImmediate(resolve));
}

function ready(token, title = 'Montierte Außenkamera') {
  return {token, status: 'ready', title, category: 'Videoüberwachung', description: 'Referenzmontage'};
}

test('two selected photos are prepared individually and committed together', async () => {
  const prepared = [];
  let saved;
  const h = harness({handle: async (url, options) => {
    assert.equal(options.credentials, 'same-origin');
    if (url.endsWith('/prepare')) {
      const token = options.body.get('token'); prepared.push(token);
      assert.equal(options.body.getAll('image').length, 1);
      return response({token, status: 'queued'});
    }
    if (url.endsWith('/commit')) { saved = JSON.parse(options.body); return response({count: saved.items.length}); }
    return response(ready(url.split('/').pop()));
  }});
  await h.choose(['Kamera-A.jpg', 'Kamera-B.jpg']);
  await h.upload();
  assert.equal(prepared.length, 2);
  assert.notEqual(prepared[0], prepared[1]);
  assert.equal(h.list.children.length, 2);
  assert.equal(h.commit.hidden, false);
  await h.save();
  assert.deepEqual(saved.items.map(item => item.token), prepared);
  assert.equal(new Set(saved.items.map(item => item.token)).size, 2);
  assert.equal(h.commit.hidden, true);
  assert.match(h.message.textContent, /2 Fotos gespeichert/);
});

test('a rejected file does not prevent another file from being saved', async () => {
  const requests = [];
  let saved;
  const h = harness({handle: async (url, options) => {
    if (url.endsWith('/prepare')) {
      const name = options.body.get('image').name; requests.push(name);
      return name === 'Zu-gross.jpg' ? response({}, 413) : response(ready(options.body.get('token')));
    }
    if (url.endsWith('/commit')) { saved = JSON.parse(options.body); return response({count: saved.items.length}); }
    throw Error('Unexpected request ' + url);
  }});
  await h.choose(['Zu-gross.jpg', 'Kamera.jpg']);
  await h.upload();
  assert.deepEqual(requests, ['Zu-gross.jpg', 'Kamera.jpg']);
  assert.match(h.list.children[0].children.at(-1).textContent, /12 MB/);
  assert.equal(h.commit.hidden, false);
  assert.equal(h.start.disabled, false);
  await h.save();
  assert.equal(saved.items.length, 1);
  assert.equal(saved.items[0].title, 'Montierte Außenkamera');
});

test('retrying a lost commit response preserves batch and tokens without new uploads', async () => {
  const saves = [], serverPhotos = new Map();
  let uploads = 0;
  const h = harness({handle: async (url, options) => {
    if (url.endsWith('/prepare')) { uploads++; return response(ready(options.body.get('token'))); }
    if (url.endsWith('/commit')) {
      const data = JSON.parse(options.body); saves.push(data);
      data.items.forEach(item => serverPhotos.set(item.token, item));
      if (saves.length === 1) throw new TypeError('Network connection interrupted');
      return response({count: data.items.length});
    }
    throw Error('Unexpected request ' + url);
  }});
  await h.choose(['A.jpg', 'B.jpg']);
  await h.upload();
  await h.save();
  assert.equal(h.commit.hidden, false);
  assert.equal(h.commit.disabled, false);
  assert.equal(JSON.parse(h.stored.get(storageKey)).rows.length, 2);
  await h.save();
  assert.deepEqual(saves[1], saves[0]);
  assert.equal(serverPhotos.size, 2);
  assert.equal(uploads, 2);
  assert.equal(h.commit.hidden, true);
});

test('adding another selection retains prepared photos and enforces the total of twenty', async () => {
  let saved;
  const h = harness({handle: async (url, options) => {
    if (url.endsWith('/prepare')) return response(ready(options.body.get('token')));
    if (url.endsWith('/commit')) { saved = JSON.parse(options.body); return response({count: saved.items.length}); }
    throw Error('Unexpected request ' + url);
  }});
  await h.choose(['A.jpg']); await h.upload();
  const tokenA = JSON.parse(h.stored.get(storageKey)).rows[0].token;
  await h.choose(['B.jpg']); await h.upload();
  assert.equal(h.list.children.length, 2);
  await h.choose(Array.from({length: 19}, (_, index) => 'extra-' + index + '.jpg'));
  assert.equal(h.list.children.length, 2);
  assert.match(h.message.textContent, /20/);
  await h.save();
  assert.equal(saved.items.length, 2);
  assert.ok(saved.items.some(item => item.token === tokenA));
});

test('upload token is persisted before request and resuming restores a lost preparation response', async () => {
  const server = new Map();
  const stored = new Map();
  let uploads = 0;
  const handle = async (url, options, session) => {
    if (url.endsWith('/prepare')) {
      uploads++;
      const token = options.body.get('token');
      assert.ok(JSON.parse(session.get(storageKey)).rows.some(row => row.token === token), 'recoverable token must exist before the upload is sent');
      server.set(token, ready(token));
      throw new TypeError('Upload response lost');
    }
    const token = url.split('/').pop();
    assert.ok(server.has(token));
    return response(server.get(token));
  };
  const initial = harness({handle, stored});
  await initial.choose(['A.jpg']); await initial.upload();
  assert.equal(uploads, 1);
  const restored = harness({handle, stored});
  await flush();
  assert.equal(restored.list.children.length, 1);
  assert.equal(restored.requests.length, 0, 'reload alone must not restart image analysis');
  await restored.upload();
  assert.equal(restored.commit.hidden, false);
  assert.equal(uploads, 1);
  assert.ok(restored.requests.some(request => request.url.endsWith('/' + [...server.keys()][0])));
});

test('pending commit locks fields, removal and file selection until saved', async () => {
  let release, sent;
  const waiting = new Promise(resolve => { release = resolve; });
  const h = harness({handle: async (url, options) => {
    if (url.endsWith('/prepare')) return response(ready(options.body.get('token')));
    if (url.endsWith('/commit')) { sent = JSON.parse(options.body); return waiting; }
    throw Error('Unexpected request ' + url);
  }});
  await h.choose(['A.jpg']); await h.upload();
  const saving = h.save(); await flush();
  assert.equal(h.input.disabled, true);
  assert.equal(h.start.disabled, true);
  assert.equal(h.commit.disabled, true);
  const card = h.list.children[0];
  const title = card.children.find(child => child.id === 'photo-0-title');
  const remove = card.children.find(child => child.textContent === 'Aus Auswahl entfernen');
  assert.equal(title.disabled, true);
  assert.equal(remove.disabled, true);
  // Also reject stale or programmatically dispatched events during the request.
  title.value = 'Darf nicht als gespeichert erscheinen'; await title.emit('input');
  await remove.emit('click');
  await h.choose(['B.jpg']);
  await h.commit.emit('click');
  assert.equal(h.requests.filter(request => request.url.endsWith('/commit')).length, 1);
  assert.equal(h.list.children.length, 1);
  release(response({count: 1})); await saving;
  assert.equal(h.input.disabled, false);
  assert.equal(h.start.disabled, false);
  assert.equal(h.commit.hidden, true);
  const saved = JSON.parse(h.stored.get(storageKey)).rows;
  assert.equal(saved.length, 1);
  assert.equal(saved[0].title, sent.items[0].title);
  assert.equal(saved[0].status, 'committed');
});

test('definitively rejected commit unlocks review fields and allows local removal without deletion request', async () => {
  const h = harness({handle: async (url, options) => {
    if (url.endsWith('/prepare')) return response(ready(options.body.get('token')));
    if (url.endsWith('/commit')) return response({error: 'Bitte Angaben prüfen.'}, 400);
    throw Error('Unexpected request ' + url);
  }});
  await h.choose(['A.jpg']); await h.upload(); await h.save();
  assert.equal(h.input.disabled, false);
  assert.equal(h.list.children[0].children.find(child => child.id === 'photo-0-title').disabled, false);
  const requestsBefore = h.requests.length;
  await h.list.children[0].children.find(child => child.textContent === 'Aus Auswahl entfernen').emit('click');
  assert.equal(h.list.children.length, 0);
  assert.equal(JSON.parse(h.stored.get(storageKey)).rows.length, 0);
  assert.equal(h.requests.length, requestsBefore, 'removal must never delete a library or server photo');
  assert.match(h.message.textContent, /Bibliotheksfotos bleiben erhalten/);
});

test('rejected photos can be removed to free the twenty-photo limit and stay removed after reload', async () => {
  const stored = new Map();
  const h = harness({stored, handle: async () => response({}, 413)});
  await h.choose(Array.from({length: 20}, (_, index) => 'large-' + index + '.jpg'));
  await h.upload();
  assert.equal(h.list.children.length, 20);
  await h.list.children[0].children.find(child => child.textContent === 'Aus Auswahl entfernen').emit('click');
  assert.equal(h.list.children.length, 19);
  const restored = harness({stored, handle: async () => { throw Error('No request expected'); }});
  assert.equal(restored.list.children.length, 19);
  await restored.choose(['Replacement.jpg']);
  assert.equal(restored.list.children.length, 20);
  assert.ok(JSON.parse(stored.get(storageKey)).rows.some(row => row.sourceName === 'Replacement.jpg'));
});

test('upload start keeps prepared review controls editable while removal remains locked', async () => {
  let release;
  const waiting = new Promise(resolve => { release = resolve; });
  const h = harness({handle: async (url, options) => {
    if (url.endsWith('/prepare') && options.body.get('image').name === 'A.jpg') return response(ready(options.body.get('token')));
    if (url.endsWith('/prepare')) { await waiting; return response(ready(options.body.get('token'))); }
    throw Error('Unexpected request ' + url);
  }});
  await h.choose(['A.jpg']); await h.upload(); await h.choose(['B.jpg']);
  await h.form.emit('submit'); await flush();
  assert.equal(h.input.disabled, true);
  const card = h.list.children[0];
  assert.equal(card.children.find(child => child.id === 'photo-0-title').disabled, false);
  const description = card.children.find(child => child.id === 'photo-0-description');
  description.value = 'Eigene Beschreibung während Foto B hochlädt'; await description.emit('input');
  assert.equal(card.children.find(child => child.textContent === 'Aus Auswahl entfernen').disabled, true);
  release(); await flush();
  assert.equal(h.input.disabled, false);
  assert.equal(h.commit.disabled, false);
  assert.equal(h.list.children[0].children.find(child => child.id === 'photo-0-description').value, 'Eigene Beschreibung während Foto B hochlädt');
});


function descriptionControl(h,index){ return h.list.children[index].children.find(n=>n.tag==='textarea'); }
function titleControl(h,index){ return h.list.children[index].children.find(n=>n.tag==='input'); }
function categoryControl(h,index){ return h.list.children[index].children.find(n=>n.tag==='select'); }

test('ready and queued photos remain independently editable while another suggestion is pending', async()=>{
  let release, delayed;
  const waiting=new Promise(resolve=>{release=resolve;});
  const h=harness({handle:async(url,options)=>{
    if(url.endsWith('/prepare')){
      const token=options.body.get('token');
      if(options.body.get('image').name==='A.jpg') return response(ready(token,'AI-A'));
      delayed=token; return response({token,status:'queued',title:'B',category:'',description:''});
    }
    return waiting;
  }});
  await h.choose(['A.jpg','B.jpg']); await h.upload();
  const a=descriptionControl(h,0),b=descriptionControl(h,1);
  assert.equal(a.disabled,false); assert.equal(b.disabled,false);
  a.value='Eigener Text A';await a.emit('input');
  b.value='Eigener Text B';await b.emit('input');
  const category=categoryControl(h,1);category.value='Alarmanlage';await category.emit('input');
  release(response(ready(delayed,'AI-B')));await flush();
  assert.equal(descriptionControl(h,0),a,'poll refresh must keep the existing input node');
  assert.equal(descriptionControl(h,1),b,'poll refresh must not replace the second textarea');
  assert.equal(descriptionControl(h,0).value,'Eigener Text A');
  assert.equal(descriptionControl(h,1).value,'Eigener Text B');
  assert.equal(categoryControl(h,1).value,'Alarmanlage');
  assert.equal(titleControl(h,1).value,'AI-B','untouched title may receive the suggestion');
});

test('twenty descriptions are committed with their own photo tokens',async()=>{
  let sent;
  const h=harness({handle:async(url,options)=>{
    if(url.endsWith('/prepare'))return response(ready(options.body.get('token')));
    if(url.endsWith('/commit')){sent=JSON.parse(options.body);return response({count:sent.items.length});}
    throw Error('Unexpected request');
  }});
  await h.choose(Array.from({length:20},(_,i)=>'Bild-'+i+'.jpg'));await h.upload();
  for(let i=0;i<20;i++){const d=descriptionControl(h,i);assert.equal(d.disabled,false);d.value='Manuelle Beschreibung '+i;await d.emit('input');}
  await h.save();
  assert.equal(sent.items.length,20);
  assert.equal(new Set(sent.items.map(i=>i.token)).size,20);
  assert.deepEqual(sent.items.map(i=>i.description),Array.from({length:20},(_,i)=>'Manuelle Beschreibung '+i));
});

test('lost commit response keeps the exact payload frozen until idempotent retry',async()=>{
  const sent=[];
  const h=harness({handle:async(url,options)=>{
    if(url.endsWith('/prepare'))return response(ready(options.body.get('token')));
    if(url.endsWith('/commit')){
      sent.push(JSON.parse(options.body));
      if(sent.length===1)throw new TypeError('Connection lost after server accepted');
      return response({count:sent.at(-1).items.length});
    }
    throw Error('Unexpected request');
  }});
  await h.choose(['A.jpg']);await h.upload();await h.save();
  const d=descriptionControl(h,0);assert.equal(d.disabled,true);
  d.value='Dieser spätere Text gehört nicht zur eingefrorenen Bestätigung';await d.emit('input');
  await h.save();
  assert.deepEqual(sent[1],sent[0]);
  assert.equal(h.commit.hidden,true);
});

test('all files are uploaded before classification polling begins', async () => {
  const events = [];
  const h = harness({handle: async (url, options) => {
    if (url.endsWith('/prepare')) {
      events.push('prepare:' + options.body.get('image').name);
      return response({token: options.body.get('token'), status: 'queued'});
    }
    events.push('poll');
    return response(ready(url.split('/').pop()));
  }});
  await h.choose(['A.jpg', 'B.jpg', 'C.jpg']); await h.upload();
  assert.deepEqual(events.slice(0, 3), ['prepare:A.jpg', 'prepare:B.jpg', 'prepare:C.jpg']);
  assert.equal(events.filter(event => event === 'poll').length, 3);
});

test('new photo descriptions remain editable and survive their preparation response', async () => {
  let release, token;
  const waiting = new Promise(resolve => { release = resolve; });
  const h = harness({handle: async (url, options) => {
    assert.ok(url.endsWith('/prepare'));
    token = options.body.get('token');
    return waiting;
  }});
  await h.choose(['A.jpg']);
  const control = descriptionControl(h, 0);
  assert.equal(control.disabled, false);
  control.value = 'Vor dem Hochladen selbst beschrieben'; await control.emit('input');
  await h.upload();
  assert.equal(descriptionControl(h, 0), control);
  assert.equal(control.disabled, false);
  release(response(ready(token))); await flush();
  assert.equal(descriptionControl(h, 0).value, 'Vor dem Hochladen selbst beschrieben');
});

test('queued manually completed photo can be saved before inference returns', async () => {
  let release, sent, token;
  const waiting = new Promise(resolve => { release = resolve; });
  const h = harness({handle: async (url, options) => {
    if (url.endsWith('/prepare')) {
      token = options.body.get('token');
      return response({token, status: 'queued', title: 'A', category: '', description: ''});
    }
    if (url.endsWith('/commit')) { sent = JSON.parse(options.body); return response({count: sent.items.length}); }
    return waiting;
  }});
  await h.choose(['A.jpg']); await h.upload();
  const category = categoryControl(h, 0); category.value = 'Alarmanlage'; await category.emit('input');
  const description = descriptionControl(h, 0); description.value = 'Manuell geprüft'; await description.emit('input');
  assert.equal(h.commit.disabled, false);
  await h.save();
  assert.equal(sent.items.length, 1);
  assert.equal(sent.items[0].manual, true);
  assert.equal(sent.items[0].description, 'Manuell geprüft');
  release(response(ready(token))); await flush();
  const saved = JSON.parse(h.stored.get(storageKey));
  assert.equal(saved.rows[0].status, 'committed');
  assert.equal(saved.rows[0].description, 'Manuell geprüft');
});

test('successful partial saves receive distinct batch identities', async () => {
  const sent = [];
  const h = harness({handle: async (url, options) => {
    if (url.endsWith('/prepare')) return response(ready(options.body.get('token')));
    if (url.endsWith('/commit')) { sent.push(JSON.parse(options.body)); return response({count: sent.at(-1).items.length}); }
    throw Error('Unexpected request');
  }});
  await h.choose(['A.jpg', 'B.jpg']); await h.upload();
  function check(index) {
    return h.list.children[index].children.find(child => child.tag === 'label' && child.children.some(n => n.type === 'checkbox')).children.find(n => n.type === 'checkbox');
  }
  const second = check(1); second.checked = false; await second.emit('change');
  await h.save();
  second.checked = true; await second.emit('change');
  await h.save();
  assert.equal(sent.length, 2);
  assert.notEqual(sent[0].batch, sent[1].batch);
  assert.equal(sent[0].items.length, 1);
  assert.equal(sent[1].items.length, 1);
  assert.notEqual(sent[0].items[0].token, sent[1].items[0].token);
});

test('pending commit restored after reload retries frozen fields without uploading again', async () => {
  const stored = new Map(), sent = [];
  const handle = async (url, options) => {
    if (url.endsWith('/prepare')) return response(ready(options.body.get('token')));
    if (url.endsWith('/commit')) {
      sent.push(JSON.parse(options.body));
      if (sent.length === 1) throw new TypeError('Response lost');
      return response({count: sent.at(-1).items.length});
    }
    throw Error('Unexpected request');
  };
  const first = harness({handle, stored});
  await first.choose(['A.jpg']); await first.upload(); await first.save();
  assert.ok(JSON.parse(stored.get(storageKey)).pendingCommit);
  const restored = harness({handle, stored});
  assert.equal(descriptionControl(restored, 0).disabled, true);
  assert.equal(restored.requests.length, 0);
  await restored.save();
  assert.deepEqual(sent[1], sent[0]);
  assert.equal(restored.requests.some(request => request.url.endsWith('/prepare')), false);
  assert.equal(JSON.parse(stored.get(storageKey)).pendingCommit, null);
});

test('specific server JSON error is shown and definite rejection permits editing', async () => {
  const h = harness({handle: async (url, options) => {
    if (url.endsWith('/prepare')) return response(ready(options.body.get('token')));
    return response({error: 'Bitte für jedes ausgewählte Foto eine Kategorie angeben.'}, 400);
  }});
  await h.choose(['A.jpg']); await h.upload(); await h.save();
  assert.match(h.message.textContent, /für jedes ausgewählte Foto eine Kategorie/);
  assert.equal(descriptionControl(h, 0).disabled, false);
  assert.equal(JSON.parse(h.stored.get(storageKey)).pendingCommit, null);
});
