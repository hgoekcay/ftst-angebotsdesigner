/* Prepare private PDF in the authenticated document; no public Ingress links. */
(() => {
  const panel = document.querySelector('[data-offer-delivery]');
  if (!panel) return;
  const result = panel.querySelector('[data-delivery-result]');
  let objectUrl;
  let busy = false;
  panel.addEventListener('input', () => {
    result.replaceChildren();
    if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = null; }
  });
  const element = (tag, text, parent = result) => {
    const node = document.createElement(tag);
    node.textContent = text;
    parent.append(node);
    return node;
  };
  const phoneNumber = value => {
    let number = value.trim().replace(/[\s().-]/g, '');
    if (number.startsWith('00')) number = '+' + number.slice(2);
    else if (/^0[1-9]/.test(number)) number = '+49' + number.slice(1);
    if (!/^\+[1-9]\d{6,14}$/.test(number)) throw Error('Bitte eine gültige Telefonnummer mit Ländervorwahl eingeben, z. B. +49 171 1234567.');
    return number.slice(1);
  };
  panel.addEventListener('click', async event => {
    const button = event.target.closest('[data-deliver]');
    if (!button || busy) return;
    result.replaceChildren();
    if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = null; }
    const status = element('p', '');
    let recipient;
    const channel = button.dataset.deliver;
    const email = panel.querySelector('#delivery-email');
    const subject = panel.querySelector('#delivery-subject').value.trim();
    const message = panel.querySelector('#delivery-text').value.trim();
    try {
      if (channel === 'email') {
        recipient = email.value.trim();
        if (!recipient || !email.checkValidity() || /[\r\n,;]/.test(recipient)) throw Error('Bitte eine gültige E-Mail-Adresse des Kunden eingeben.');
      } else recipient = phoneNumber(panel.querySelector('#delivery-phone').value);
    } catch (error) { status.textContent = error.message; return; }
    busy = true;
    panel.querySelectorAll('[data-deliver], input, textarea').forEach(node => { node.disabled = true; });
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    status.textContent = 'PDF wird für den Versand vorbereitet …';
    try {
      const response = await fetch(panel.dataset.pdfUrl, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
      if (response.status === 401 || response.status === 403) throw Error('Anmeldung abgelaufen. Bitte die Angebotsapp über Home Assistant neu öffnen.');
      if (!response.ok || !(response.headers.get('Content-Type') || '').includes('application/pdf')) throw Error('PDF konnte nicht vorbereitet werden. Bitte erneut versuchen.');
      const blob = await response.blob();
      if (await blob.slice(0, 5).text() !== '%PDF-') throw Error('Keine gültige PDF erhalten. Es wurde nichts versendet.');
      const file = new File([blob], panel.dataset.filename, {type: 'application/pdf'});
      objectUrl = URL.createObjectURL(blob);
      status.textContent = 'PDF bereit. Empfänger: ' + (channel === 'email' ? recipient : '+' + recipient) + '. Noch nicht versendet.';
      const save = element('a', '1. PDF speichern');
      save.className = 'btn light'; save.href = objectUrl; save.download = file.name;
      const open = element('a', channel === 'email' ? '2. E-Mail mit Empfänger öffnen' : '2. WhatsApp-Chat öffnen');
      open.className = 'btn';
      open.href = channel === 'email'
        ? 'mailto:' + encodeURIComponent(recipient) + '?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(message)
        : 'https://wa.me/' + recipient + '?text=' + encodeURIComponent(message);
      if (channel === 'whatsapp') { open.target = '_blank'; open.rel = 'noopener noreferrer'; }
      element('p', 'Die gespeicherte PDF in der geöffneten Nachricht als Anhang hinzufügen und dort senden. Der Empfänger und Nachrichtentext werden übernommen; der Anhang wird durch diesen Link nicht automatisch eingefügt.');
      if (navigator.share && navigator.canShare && navigator.canShare({files: [file]})) {
        const share = element('button', 'PDF direkt an eine App teilen');
        share.type = 'button'; share.className = 'btn light';
        element('p', 'Alternativ im Teilen-Menü ' + (channel === 'email' ? 'Ihre E-Mail-App' : 'WhatsApp') + ' wählen. Hier müssen Sie den oben angezeigten Empfänger selbst auswählen.');
        share.addEventListener('click', async () => {
          try {
            await navigator.share({files: [file], title: subject, text: message});
            status.textContent = 'An die ausgewählte App übergeben. Bitte den Versand dort prüfen.';
          } catch (error) {
            status.textContent = error.name === 'AbortError' ? 'Teilen abgebrochen. Es wird kein Versand bestätigt.' : 'Teilen nicht verfügbar. Bitte PDF speichern und als Anhang hinzufügen.';
          }
        });
      }
    } catch (error) {
      status.textContent = error.name === 'AbortError' ? 'PDF-Abruf hat zu lange gedauert. Bitte erneut versuchen.' : error.message;
    } finally {
      clearTimeout(timer); busy = false;
      panel.querySelectorAll('[data-deliver], input, textarea').forEach(node => { node.disabled = false; });
    }
  });
  window.addEventListener('pagehide', event => { if (!event.persisted && objectUrl) URL.revokeObjectURL(objectUrl); });
})();
