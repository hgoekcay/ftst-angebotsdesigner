/* Run with node --test tests/barcode_browser.cjs. No camera/network required. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '../ftst_angebotsdesigner/static/barcode-scan.js'), 'utf8');

function harness({storage = new Map(), fetcher = async () => { throw Error('offline'); }, readerError = false} = {}) {
  function element() {
    return {listeners: {}, children: [], style: {}, hidden: false, disabled: false, value: '',
      addEventListener(name, fn) { this.listeners[name] = fn; },
      append(node) { this.children.push(node); }, replaceChildren() { this.children = []; },
      reportValidity() { return true; }};
  }
  const ids = Object.fromEntries(['barcode-screen', 'barcode-lookup', 'barcode-video', 'barcode-start',
    'barcode-stop', 'barcode-camera-status', 'barcode-issue', 'barcode-pending', 'barcode-total', 'barcode-selection'].map(id => [id, element()]));
  ids['barcode-screen'].dataset = {statusBase: '/inventory/scan/operations/', storageKey: 'test'};
  ids['barcode-lookup'].elements = {order: element(), code: element()};
  let selected = 0, camera = 0, stopped = 0;
  ids['barcode-lookup'].requestSubmit = () => { selected++; };
  const form = ids['barcode-issue'];
  form.elements = [element(), element()]; form.elements.scan_quantity = form.elements[0];
  form.dataset = {factor: '1000', unit: 'Stück'};
  const document = {hidden: false, listeners: {}, getElementById: id => ids[id], createElement: element,
    addEventListener(name, fn) { this.listeners[name] = fn; }};
  const control = {stop() { stopped++; }};
  class Reader {
    async decodeFromConstraints(constraints, video, callback) {
      camera++; assert.equal(constraints.audio, false);
      if (readerError) throw Error('NotAllowed');
      video.srcObject = {getTracks: () => [control]};
      callback({getText: () => '0012345678905'}, null, control);
      callback({getText: () => '0012345678905'}, null, control);
      return control;
    }
  }
  const window = {isSecureContext: true, ZXingBrowser: {BrowserMultiFormatOneDReader: Reader},
    location: {pathname: '/inventory/scan', reload() {}}, addEventListener() {}};
  const context = {window, document, navigator: {mediaDevices: {getUserMedia() {}}},
    sessionStorage: {getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k)},
    URLSearchParams, FormData: class { constructor() { return [['operation', 'fixed-id'], ['scan_quantity', '2']]; } },
    fetch: fetcher, console};
  vm.runInNewContext(script, context);
  return {ids, storage, context, selected: () => selected, camera: () => camera, stopped: () => stopped};
}

test('camera is opt-in; repeated frames select only once and never book', async () => {
  let calls = 0;
  const h = harness({fetcher: async () => { calls++; }});
  assert.equal(h.camera(), 0);
  await h.ids['barcode-start'].listeners.click();
  assert.equal(h.camera(), 1);
  assert.equal(h.selected(), 1);
  assert.equal(h.ids['barcode-lookup'].elements.code.value, '0012345678905');
  assert.equal(h.ids['barcode-issue'].elements.scan_quantity.value, '');
  assert.ok(h.stopped() >= 1);
  assert.equal(calls, 0);
});

test('denied camera keeps typed-code fallback', async () => {
  const h = harness({readerError: true});
  await h.ids['barcode-start'].listeners.click();
  assert.match(h.ids['barcode-camera-status'].textContent, /Codeeingabe/);
  assert.equal(h.ids['barcode-start'].disabled, false);
  assert.equal(h.ids['barcode-lookup'].elements.code.disabled, false);
});

test('lost response persists the same operation and retries exact body after status check', async () => {
  const storage = new Map();
  const first = harness({storage});
  await first.ids['barcode-issue'].listeners.submit({preventDefault() {}});
  const saved = JSON.parse(storage.get('test'));
  assert.equal(saved.operation, 'fixed-id');
  const calls = [];
  const second = harness({storage, fetcher: async (url, options) => {
    calls.push({url, options});
    return {ok: true, json: async () => options.method === 'POST'
      ? {found: true, quantity: '2', article: 'Kontakt', unit: 'Stück', stock: '6'} : {found: false}};
  }});
  assert.equal(second.ids['barcode-issue'].elements[0].disabled, true);
  const retry = second.ids['barcode-pending'].children.find(n => n.textContent === 'Denselben Vorgang erneut senden');
  await retry.listeners.click();
  assert.equal(calls.length, 2);
  assert.match(calls[0].url, /operations\/fixed-id$/);
  assert.equal(calls[1].options.body, saved.body);
  assert.equal(storage.has('test'), false);
  assert.equal(second.ids['barcode-selection'].hidden, true);
});

test('missing browser storage prevents a booking request', async () => {
  let calls = 0;
  const h = harness({fetcher: async () => { calls++; }});
  h.context.sessionStorage.setItem = () => { throw Error('quota'); };
  await h.ids['barcode-issue'].listeners.submit({preventDefault() {}});
  assert.equal(calls, 0);
  assert.match(h.ids['barcode-pending'].children[0].textContent, /Keine Übertragung/);
});

test('vendored decoder decodes synthetic EAN13 and retains leading zero', () => {
  const context = vm.createContext({window: {}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../ftst_angebotsdesigner/static/vendor/zxing-browser-0.2.1.min.js'), 'utf8'), context);
  const reader = new context.ZXingBrowser.BrowserMultiFormatOneDReader(new Map([[2, [2, 3, 4, 6, 7, 8]]]));
  const code = '0012345678905';
  const left = ['0001101', '0011001', '0010011', '0111101', '0100011', '0110001', '0101111', '0111011', '0110111', '0001011'];
  const right = left.map(s => s.replace(/[01]/g, d => d === '0' ? '1' : '0'));
  // First digit zero uses six L encodings on the left.
  const bars = '0'.repeat(12) + '101' + [...code.slice(1, 7)].map(d => left[Number(d)]).join('') +
    '01010' + [...code.slice(7)].map(d => right[Number(d)]).join('') + '101' + '0'.repeat(12);
  const width = bars.length * 3, height = 80;
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const pos = (y * width + x) * 4;
    const color = bars[Math.floor(x / 3)] === '1' ? 0 : 255;
    data[pos] = data[pos + 1] = data[pos + 2] = color; data[pos + 3] = 255;
  }
  const result = reader.decodeFromCanvas({width, height, getContext: () => ({getImageData: () => ({data})})});
  assert.equal(result.getText(), code);
});
