const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync(require('node:path').join(__dirname, '../ftst_angebotsdesigner/static/pdf-download.js'), 'utf8');
function harness(status, type, bytes) {
  let handler, options, urlCount = 0;
  const node = () => ({children: [], dataset: {}, style: {}, append(x) {this.children.push(x);}, setAttribute() {}, addEventListener() {}});
  const link = node(); link.href = 'https://example.invalid/ingress/offer/42/pdf'; link.dataset.pdf = 'FTST-42.pdf'; link.after = x => link.box = x;
  vm.runInNewContext(script, {
    document: {addEventListener: (name, fn) => handler = fn, createElement: node},
    fetch: async (url, opts) => {options = opts; return {status, ok: status === 200, headers: {get: () => type}, blob: async () => new Blob([bytes])};},
    Blob, File, AbortController, setTimeout, clearTimeout,
    URL: {createObjectURL: () => {urlCount++; return 'blob:local-pdf';}, revokeObjectURL() {}},
    navigator: {}, window: {addEventListener() {}},
  });
  return {link, run: () => handler({target: {closest: () => link}, preventDefault() {}}), options: () => options, urls: () => urlCount};
}
test('401 stays in app and never becomes a downloadable file', async () => {
  const h = harness(401, 'text/plain', '401: Unauthorized'); await h.run();
  assert.match(h.link.box.children[0].textContent, /Anmeldung ist abgelaufen/);
  assert.equal(h.urls(), 0); assert.equal(h.link.box.children.length, 1);
  assert.equal(h.options().credentials, 'same-origin');
});
test('HTML and invalid PDF are rejected', async () => {
  for (const [type, bytes] of [['text/html', '<html>login'], ['application/pdf', 'bad']]) {
    const h = harness(200, type, bytes); await h.run(); assert.equal(h.urls(), 0);
  }
});
test('valid PDF is offered as local file with correct filename', async () => {
  const h = harness(200, 'application/pdf', '%PDF-1.7 test'); await h.run();
  assert.equal(h.urls(), 1);
  assert.equal(h.link.box.children[1].href, 'blob:local-pdf');
  assert.equal(h.link.box.children[1].download, 'FTST-42.pdf');
  assert.equal(h.link.hidden, true);
});
