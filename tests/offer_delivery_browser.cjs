const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync(require('node:path').join(__dirname, '../ftst_angebotsdesigner/static/offer-delivery.js'), 'utf8');
function harness({email = 'kunde@example.org', phone = '0171 1234567', status = 200, type = 'application/pdf', bytes = '%PDF-1.7', shareError = null} = {}) {
  let handler, calls = 0, shares = 0, lastOptions, lastUrl;
  const node = tag => ({tag, children: [], dataset: {}, textContent: '', append(x) {this.children.push(x);}, replaceChildren() {this.children = [];}, addEventListener(name, fn) {this[name] = fn;}});
  const result = node('div');
  const fields = {'#delivery-email': {value: email, checkValidity: () => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)}, '#delivery-phone': {value: phone}, '#delivery-subject': {value: 'Angebot & Prüfung'}, '#delivery-text': {value: 'Guten Tag\nIhr Angebot'}};
  const buttons = [node('button'), node('button')];
  const panel = {dataset: {pdfUrl: '/ingress/offer/42/pdf', filename: 'FTST-42.pdf'}, querySelector: s => s === '[data-delivery-result]' ? result : fields[s], querySelectorAll: () => buttons, addEventListener: (name, fn) => {handler = fn;}};
  vm.runInNewContext(script, {document: {querySelector: () => panel, createElement: node},
    fetch: async (url, opts) => {calls++; lastUrl = url; lastOptions = opts; return {status, ok: status === 200, headers: {get: () => type}, blob: async () => new Blob([bytes])};},
    Blob, File, AbortController, setTimeout, clearTimeout,
    URL: {createObjectURL: () => 'blob:private-pdf', revokeObjectURL() {}},
    navigator: {canShare: () => true, share: async () => {shares++; if (shareError) throw {name: shareError};}}, window: {addEventListener() {}}});
  return {result, fields, calls: () => calls, shares: () => shares, options: () => lastOptions, url: () => lastUrl,
    run: channel => handler({target: {closest: () => ({dataset: {deliver: channel}})}})};
}
test('email uses customer, encoded message, authenticated PDF, never sends automatically', async () => {
  const h = harness(); await h.run('email');
  const links = h.result.children.filter(x => x.tag === 'a');
  assert.equal(links[0].href, 'blob:private-pdf');
  assert.equal(links[0].download, 'FTST-42.pdf');
  assert.match(links[1].href, /^mailto:kunde%40example.org\?subject=/);
  assert.match(links[1].href, /%26/); assert.doesNotMatch(links[1].href, /ingress/);
  assert.equal(h.options().credentials, 'same-origin'); assert.equal(h.options().cache, 'no-store');
  assert.equal(h.shares(), 0); assert.equal(h.url(), '/ingress/offer/42/pdf');
});
test('WhatsApp normalizes German and international phone numbers', async () => {
  for (const phone of ['0171 1234567', '+49 171 1234567', '0049 171 1234567']) {
    const h = harness({phone}); await h.run('whatsapp');
    assert.match(h.result.children.find(x => x.href && x.href.startsWith('https:')).href, /^https:\/\/wa.me\/491711234567\?text=/);
  }
});
test('invalid and missing recipients never fetch or create external links', async () => {
  for (const [channel, config] of [['email', {email: ''}], ['email', {email: 'a@b.de\r\nBcc:x@y.de'}], ['whatsapp', {phone: ''}], ['whatsapp', {phone: '123'}]]) {
    const h = harness(config); await h.run(channel); assert.equal(h.calls(), 0);
  }
});
test('authentication failure, HTML and invalid PDF never create links', async () => {
  for (const config of [{status: 401}, {status: 403}, {type: 'text/html'}, {bytes: 'not PDF'}]) {
    const h = harness(config); await h.run('email'); assert.equal(h.result.children.length, 1);
  }
});
test('native sharing is a second explicit action and cancellation is not reported as sent', async () => {
  const h = harness({shareError: 'AbortError'}); await h.run('whatsapp');
  assert.equal(h.shares(), 0);
  await h.result.children.find(x => x.tag === 'button').click();
  assert.equal(h.shares(), 1); assert.match(h.result.children[0].textContent, /abgebrochen/);
});
