(() => {
  const root = document.querySelector('[data-chat-status]');
  if (!root) return;
  root.querySelectorAll('[data-article-search]').forEach(input => {
    const select = document.getElementById(input.dataset.articleSearch);
    if (!select) return;
    const options = Array.from(select.options, option => option.cloneNode(true));
    input.addEventListener('input', () => {
      const chosen = select.value;
      const query = input.value.trim().toLocaleLowerCase('de');
      select.replaceChildren(...options.filter(option => !option.value || option.value === chosen || option.textContent.toLocaleLowerCase('de').includes(query)).map(option => option.cloneNode(true)));
      select.value = chosen;
    });
  });
  const log = root.querySelector('.chat-log');
  if (log) log.scrollTop = log.scrollHeight;
  if (root.dataset.busy === '1') {
    let attempts = 0;
    const poll = async () => {
      try {
        const response = await fetch(root.dataset.chatStatus, {credentials: 'same-origin', cache: 'no-store'});
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error();
        const state = await response.json();
        if (!state.busy) { location.reload(); return; }
      } catch (_) { /* Keep the saved job visible; never resubmit an action. */ }
      if (++attempts < 90) setTimeout(poll, 4000);
      else root.querySelector('[role="status"]').textContent = 'Verbindung unterbrochen. Bitte die Seite neu laden; die Aktion nicht erneut senden.';
    };
    setTimeout(poll, 2000);
  }
  root.querySelectorAll('form').forEach(form => form.addEventListener('submit', () => {
    // Do not disable the clicked named button: its action is part of the POST.
    form.setAttribute('aria-busy', 'true');
  }));
  const form = root.querySelector('[data-chat-audio]');
  const start = form.querySelector('[data-record]');
  const stop = form.querySelector('[data-stop]');
  const status = form.querySelector('[data-voice-status]');
  let recorder, stream, timer;
  const cleanup = () => { clearTimeout(timer); stream?.getTracks().forEach(track => track.stop()); };
  start.addEventListener('click', async () => {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      status.textContent = 'Aufnahme hier nicht verfügbar. Bitte eine Sprachnotiz hochladen oder mit der Handytastatur diktieren.'; return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: true});
      const mime = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm'].find(type => MediaRecorder.isTypeSupported(type));
      recorder = new MediaRecorder(stream, mime ? {mimeType: mime} : {});
      const chunks = [];
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => {
        cleanup(); start.disabled = false; stop.disabled = true;
        try {
          const type = recorder.mimeType || 'audio/webm';
          const file = new File(chunks, type.includes('mp4') ? 'Sprachnotiz.m4a' : 'Sprachnotiz.webm', {type});
          const transfer = new DataTransfer(); transfer.items.add(file);
          form.querySelector('[name="audio"]').files = transfer.files;
          status.textContent = 'Aufnahme bereit. Jetzt „Sprachnotiz erkennen“ wählen.';
        } catch (_) { status.textContent = 'Die Aufnahme konnte nicht übernommen werden. Bitte eine vorhandene Audiodatei auswählen.'; }
      };
      recorder.onerror = () => { cleanup(); start.disabled = false; stop.disabled = true; status.textContent = 'Aufnahme fehlgeschlagen. Bitte Audiodatei hochladen.'; };
      recorder.start(); start.disabled = true; stop.disabled = false;
      status.textContent = 'Aufnahme läuft … maximal 2 Minuten.';
      timer = setTimeout(() => { if (recorder.state === 'recording') recorder.stop(); }, 119000);
    } catch (_) { cleanup(); status.textContent = 'Mikrofon nicht verfügbar oder nicht freigegeben. Audiodatei hochladen oder Tastatur-Diktat verwenden.'; }
  });
  stop.addEventListener('click', () => { if (recorder?.state === 'recording') recorder.stop(); });
  window.addEventListener('pagehide', cleanup);
})();

