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
    const messageField = panel.querySelector(channel === 'email' ? '#delivery-email-text' : '#delivery-whatsapp-text');
    const message = messageField.value.trim();
    try {
      if (channel === 'email') {
        recipient = email.value.trim();
        if (!recipient || !email.checkValidity() || /[\r\n,;]/.test(recipient)) throw Error('Bitte eine gültige E-Mail-Adresse des Kunden eingeben.');
      } else {
        const phone = panel.querySelector('#delivery-phone').value.trim();
        recipient = phone ? phoneNumber(phone) : '';
      }
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
      status.textContent = 'PDF bereit. ' + (recipient ? 'Empfänger: ' + (channel === 'email' ? recipient : '+' + recipient) + '. ' : '') + 'Noch nicht versendet.';
      let canShareFiles = false;
      try { canShareFiles = Boolean(navigator.share && navigator.canShare && navigator.canShare({files: [file]})); } catch (_) { /* Use download fallback. */ }
      if (canShareFiles) {
        const share = element('button', channel === 'whatsapp' ? 'PDF an WhatsApp teilen' : 'PDF an E-Mail-App teilen');
        share.type = 'button'; share.className = 'btn';
        if (channel === 'whatsapp') share.style.background = '#16803c';
        element('p', 'Im Teilen-Menü ' + (channel === 'email' ? 'Ihre E-Mail-App' : 'WhatsApp') + ' und anschließend den Kunden auswählen. Die PDF wird als Datei übergeben. Bitte vor dem Senden den Anhang prüfen.');
        share.addEventListener('click', async () => {
          if (share.disabled) return;
          share.disabled = true;
          try {
            await navigator.share({files: [file], title: subject, text: message});
            status.textContent = 'An die ausgewählte App übergeben. Bitte den Versand dort prüfen.';
          } catch (error) {
            status.textContent = error.name === 'AbortError' ? 'Teilen abgebrochen. Es wird kein Versand bestätigt.' : 'Dateiteilen wurde vom Browser nicht erlaubt. PDF speichern und in der Nachricht als Dokument anhängen.';
          } finally { share.disabled = false; }
        });
        element('p', 'Manche Apps übernehmen beim Dateiteilen nur die PDF. Den passenden Nachrichtentext können Sie mit „Text kopieren“ ergänzen.');
      } else {
        element('p', 'Dieser Browser unterstützt das direkte Teilen von PDF-Dateien hier nicht. PDF speichern und anschließend in ' + (channel === 'email' ? 'Ihrer E-Mail' : 'WhatsApp über „+ / Büroklammer → Dokument“') + ' anhängen. Ein Chat-Link allein sendet keine PDF.');
      }
      const save = element('a', 'PDF speichern');
      save.className = canShareFiles ? 'btn light' : 'btn'; save.href = objectUrl; save.download = file.name;
      const copy = element('button', 'Text kopieren');
      copy.type = 'button'; copy.className = 'btn light';
      copy.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(message);
          status.textContent = 'Nachrichtentext kopiert. Die PDF bitte separat über Teilen oder als Dokument hinzufügen.';
        } catch (_) { status.textContent = 'Kopieren nicht verfügbar. Bitte den Nachrichtentext oben manuell markieren und kopieren.'; }
      });
      if (recipient) {
        const alternatives = element('details', '');
        element('summary', 'Empfänger direkt öffnen (PDF selbst anhängen)', alternatives);
        const open = element('a', channel === 'email' ? 'E-Mail öffnen – noch ohne Anhang' : 'WhatsApp-Chat öffnen – nur Text, keine PDF', alternatives);
        open.className = 'btn light';
        open.href = channel === 'email'
          ? 'mailto:' + encodeURIComponent(recipient) + '?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(message)
          : 'https://wa.me/' + recipient + '?text=' + encodeURIComponent(message);
        if (channel === 'whatsapp') { open.target = '_blank'; open.rel = 'noopener noreferrer'; }
        element('p', 'Die gespeicherte PDF in der geöffneten Nachricht selbst als Anhang hinzufügen. Dieser Link überträgt nur Empfänger und Text.', alternatives);
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
