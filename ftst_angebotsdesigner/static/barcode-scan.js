/* Camera and decoding remain local. Only a code or confirmed booking is sent. */
(() => {
  'use strict';
  const root = document.getElementById('barcode-screen');
  if (!root) return;
  const lookup = document.getElementById('barcode-lookup');
  const video = document.getElementById('barcode-video');
  const start = document.getElementById('barcode-start');
  const stop = document.getElementById('barcode-stop');
  const cameraMessage = document.getElementById('barcode-camera-status');
  let controls = null, epoch = 0;
  function stopCamera() {
    epoch += 1;
    if (controls) controls.stop();
    controls = null;
    if (video.srcObject) video.srcObject.getTracks().forEach(track => track.stop());
    video.srcObject = null;
    video.hidden = true;
    stop.hidden = true;
    start.disabled = false;
  }
  stop.addEventListener('click', () => {
    stopCamera();
    cameraMessage.textContent = 'Kamera gestoppt. Code eingeben oder erneut starten.';
  });
  window.addEventListener('pagehide', stopCamera);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopCamera(); });
  start.addEventListener('click', async () => {
    if (!lookup.elements.order.reportValidity()) return;
    if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.ZXingBrowser) {
      cameraMessage.textContent = 'Kamera hier nicht verfügbar. HTTPS/Browser prüfen oder Code eintippen bzw. Hardware-Scanner verwenden.';
      return;
    }
    stopCamera();
    const generation = epoch;
    start.disabled = true;
    stop.hidden = false;
    video.hidden = false;
    cameraMessage.textContent = 'Kameraerlaubnis bestätigen und einen einfachen Produktbarcode zeigen.';
    let detected = false;
    try {
      // Pinned ZXing enums: POSSIBLE_FORMATS=2; CODE_39=2, CODE_93=3,
      // CODE_128=4, EAN_8=6, EAN_13=7, ITF=8. Excluding UPC_A prevents
      // automatic removal of a leading zero from an EAN-13 result.
      const hints = new Map([[2, [2, 3, 4, 6, 7, 8]]]);
      const reader = new window.ZXingBrowser.BrowserMultiFormatOneDReader(hints);
      const opened = await reader.decodeFromConstraints(
        {audio: false, video: {facingMode: {ideal: 'environment'}, width: {ideal: 1280}}},
        video,
        (result, error, callbackControls) => {
          if (!result || detected || generation !== epoch) return;
          detected = true;
          callbackControls.stop();
          lookup.elements.code.value = result.getText();
          stopCamera();
          cameraMessage.textContent = 'Code erkannt. Kamera pausiert; noch nichts gebucht.';
          lookup.requestSubmit();
        }
      );
      if (generation !== epoch || detected) opened.stop();
      else controls = opened;
    } catch (error) {
      if (generation !== epoch) return;
      stopCamera();
      cameraMessage.textContent = 'Kamera konnte nicht gestartet werden. Berechtigung/Einbettung prüfen; Codeeingabe und Hardware-Scanner bleiben möglich.';
    }
  });

  const form = document.getElementById('barcode-issue');
  const panel = document.getElementById('barcode-pending');
  const key = root.dataset.storageKey;
  let pending = null, sending = false;
  function lockForm(lock) {
    if (form) Array.from(form.elements).forEach(element => { element.disabled = lock; });
  }
  function button(label, fn) {
    const node = document.createElement('button');
    node.className = 'btn light';
    node.style.minHeight = '44px';
    node.type = 'button'; node.textContent = label; node.addEventListener('click', fn);
    panel.append(node);
  }
  function showPending(message) {
    panel.hidden = false;
    panel.replaceChildren();
    const text = document.createElement('p'); text.textContent = message;
    panel.append(text);
    if (!pending) return;
    const link = document.createElement('a');
    link.href = root.dataset.statusBase + encodeURIComponent(pending.operation);
    link.textContent = 'Buchungsstatus für Vorgang ' + pending.operation;
    panel.append(link);
    button('Status prüfen', () => { check().catch(() => {}); });
    button('Denselben Vorgang erneut senden', async () => {
      if (sending) return;
      try { if (await check()) return; } catch (_) { return; }
      await submitPending();
    });
  }
  function success(result) {
    sessionStorage.removeItem(key);
    pending = null;
    lockForm(true);
    const selection = document.getElementById('barcode-selection');
    if (selection) selection.hidden = true;
    showPending('Server bestätigt: ' + result.quantity + ' ' + result.unit + ' ' + result.article +
      ' entnommen. Aktueller Bestand im Hauptlager: ' + result.stock + ' ' + result.unit + '.');
    button('Nächste Entnahme vorbereiten', () => { window.location.href = window.location.pathname; });
  }
  async function check() {
    if (!pending) return true;
    try {
      const response = await fetch(root.dataset.statusBase + encodeURIComponent(pending.operation),
        {headers: {Accept: 'application/json'}, cache: 'no-store', redirect: 'error'});
      if (!response.ok) throw new Error('status');
      const result = await response.json();
      if (result.found) { success(result); return true; }
      showPending('Noch nicht bestätigt. Nur diesen unveränderten Vorgang erneut senden; keine neue Entnahme anlegen.');
      return false;
    } catch (_) {
      showPending('Buchungsstatus derzeit nicht erreichbar. Ergebnis unklar; nichts erneut als neue Entnahme buchen.');
      throw new Error('offline');
    }
  }
  async function submitPending() {
    if (!pending || sending) return;
    sending = true;
    lockForm(true);
    showPending('Übertragung läuft. Bitte warten; Vorgangs-ID ist in diesem Browser-Tab gesichert.');
    try {
      const response = await fetch(window.location.pathname, {method: 'POST',
        headers: {Accept: 'application/json', 'Content-Type': 'application/x-www-form-urlencoded'},
        body: pending.body, redirect: 'error'});
      const result = await response.json();
      if (response.ok && result.found) success(result);
      else if (result.already_recorded) {
        showPending('Vorgangs-ID wurde bereits gebucht, aber die Eingaben unterscheiden sich. Originalbuchung über den Status oder das Lagerjournal prüfen; keine neue Entnahme anlegen.');
      }
      else if ((response.status === 400 || response.status === 409) && result.rejected) {
        // Structured rejection is from the ledger route, not an uncertain transport error.
        sessionStorage.removeItem(key);
        pending = null;
        showPending('Nicht gebucht: ' + result.error + ' Bitte aktuellen Bestand neu laden und Eingaben prüfen.');
        button('Aktuellen Stand laden', () => window.location.reload());
      } else throw new Error('uncertain');
    } catch (_) {
      showPending('Keine sichere Serverbestätigung. Vorgang bleibt gespeichert: Status prüfen oder exakt denselben Vorgang wiederholen.');
    } finally { sending = false; }
  }
  try {
    pending = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (pending && (typeof pending.operation !== 'string' || typeof pending.body !== 'string')) throw new Error('pending');
    if (pending) { lockForm(true); showPending('Ein früherer Vorgang wartet auf Bestätigung. Zuerst dessen Status prüfen.'); }
  } catch (_) {
    lockForm(true);
    showPending('Vorgangsspeicher nicht lesbar. Vor weiterer Entnahme Lagerjournal prüfen.');
  }
  if (form) {
    form.elements.scan_quantity.addEventListener('input', () => {
      const n = Number(form.elements.scan_quantity.value.replace(',', '.'));
      document.getElementById('barcode-total').textContent = Number.isFinite(n) && n > 0
        ? 'Zur Bestätigung: ' + (n * Number(form.dataset.factor) / 1000).toLocaleString('de-DE') + ' ' + form.dataset.unit + ' aus dem Hauptlager.'
        : 'Gültige Menge eingeben; noch nichts gebucht.';
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (pending || sending) return;
      const body = new URLSearchParams(new FormData(form));
      pending = {operation: body.get('operation'), body: body.toString()};
      try { sessionStorage.setItem(key, JSON.stringify(pending)); }
      catch (_) { pending = null; showPending('Vorgangs-ID konnte nicht gesichert werden. Keine Übertragung erfolgt. Browserspeicher prüfen.'); return; }
      await submitPending();
    });
  }
})();
