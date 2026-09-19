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

test('failed commit unlocks review fields and allows local removal without deletion request', async () => {
  const h = harness({handle: async (url, options) => {
    if (url.endsWith('/prepare')) return response(ready(options.body.get('token')));
    if (url.endsWith('/commit')) throw new TypeError('Network interruption');
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

test('upload start immediately locks previously prepared review controls', async () => {
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
  assert.equal(card.children.find(child => child.id === 'photo-0-title').disabled, true);
  assert.equal(card.children.find(child => child.textContent === 'Aus Auswahl entfernen').disabled, true);
  release(); await flush();
  assert.equal(h.input.disabled, false);
  assert.equal(h.commit.disabled, false);
});
