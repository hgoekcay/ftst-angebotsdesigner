(() => {
  const form = document.getElementById('photo-batch');
  if (!form) return;
  const files = form.querySelector('input[type=file]');
  const list = document.getElementById('photo-review');
  const message = document.getElementById('photo-progress');
  const start = form.querySelector('button');
  const save = document.getElementById('photo-commit');
  const categories = JSON.parse(form.dataset.categories);
  const root = form.dataset.endpoint;
  const storageKey = 'ftst-photo-batch:' + root;
  let rows = [], running = false;
  let batch = crypto.randomUUID().replaceAll('-', '');
  const uid = () => crypto.randomUUID().replaceAll('-', '');
  const persist = () => { try { sessionStorage.setItem(storageKey, JSON.stringify({batch, rows: rows.map(({token, title, category, description, status, selected, uploaded, uncertain, sourceName, size, modified}) => ({token, title, category, description, status, selected, uploaded, uncertain, sourceName, size, modified}))})); } catch (_) {} };
  const node = (tag, text, className) => { const n = document.createElement(tag); if (text) n.textContent = text; if (className) n.className = className; return n; };
  async function api(url, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 60000);
    try {
      const response = await fetch(url, {...options, credentials: 'same-origin', signal: controller.signal});
      if (!response.ok) {
        if (response.status === 404) { const error = Error('Upload noch nicht auf dem Server. Bitte ursprüngliche Datei erneut auswählen.'); error.status = 404; throw error; }
        if (response.status === 401 || response.status === 403) throw Error('Bitte FTST Angebote in Home Assistant neu öffnen.');
        if (response.status === 413) throw Error('Foto zu groß: höchstens 12 MB pro Datei.');
        if (response.status === 400) throw Error('Bitte JPG, PNG oder WebP verwenden (höchstens 25 Megapixel) und alle Angaben prüfen.');
        throw Error('Vorgang nicht abgeschlossen (HTTP ' + response.status + '). Bitte erneut versuchen.');
      }
      if (!(response.headers.get('Content-Type') || '').includes('application/json')) throw Error('Anmeldung oder Verbindung prüfen und erneut versuchen.');
      return await response.json();
    } finally { clearTimeout(timer); }
  }
  function render() {
    list.replaceChildren();
    rows.forEach((r, index) => {
      const card = node('article', '', 'card photo-review-card');
      const image = node('img'); image.alt = r.title || ('Foto ' + (index + 1)); image.className = 'material-preview';
      image.src = r.preview || root + '/' + r.token + '/preview'; card.append(image);
      const checkLabel = node('label', ' Dieses Foto übernehmen');
      const check = node('input'); check.type = 'checkbox'; check.checked = r.selected !== false; check.disabled = running || r.status !== 'ready'; check.style.width = 'auto';
      check.addEventListener('change', () => { if (running) return; r.selected = check.checked; persist(); }); checkLabel.prepend(check); card.append(checkLabel);
      const title = node('input'); title.value = r.title || ''; title.maxLength = 200;
      const description = node('textarea'); description.value = r.description || ''; description.maxLength = 2000;
      const category = node('select'); category.append(new Option('Bitte zuordnen', '')); categories.forEach(c => category.append(new Option(c, c))); category.value = r.category || '';
      [['Bildtitel', title, 'title'], ['Angebotsart', category, 'category'], ['Beschreibung', description, 'description']].forEach(([label, control, key]) => {
        const id = 'photo-' + index + '-' + key; control.id = id;
        const lab = node('label', label); lab.htmlFor = id;
        control.disabled = running || r.status !== 'ready'; control.addEventListener('input', () => { if (running) return; r[key] = control.value; persist(); });
        card.append(lab, control);
      });
      if (r.status !== 'committed') {
        const remove = node('button', 'Aus Auswahl entfernen', 'btn light'); remove.type = 'button'; remove.disabled = running;
        remove.addEventListener('click', () => {
          if (running) return;
          rows = rows.filter(row => row !== r);
          if (r.preview) URL.revokeObjectURL(r.preview);
          files.value = ''; persist(); render();
          message.textContent = 'Foto aus dieser Auswahl entfernt. Gespeicherte Bibliotheksfotos bleiben erhalten.';
        });
        card.append(remove);
      }
      const status = node('p', r.message || (r.status === 'committed' ? 'Bereits gespeichert.' : 'Bereit zum Hochladen.')); status.setAttribute('role', 'status'); card.append(status); list.append(card);
    });
    save.hidden = !rows.some(r => r.status === 'ready'); save.disabled = running;
  }
  async function process() {
    if (running) return;
    running = true; start.disabled = true; files.disabled = true; save.disabled = true; render();
    let failure = false;
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i]; if (r.status === 'ready' || r.status === 'committed') continue;
      message.textContent = 'Foto ' + (i + 1) + ' von ' + rows.length + ': hochladen und lokal erkennen …';
      try {
        if (!r.uploaded && r.uncertain) {
          try { Object.assign(r, await api(root + '/' + r.token), {uploaded:true, uncertain:false}); persist(); }
          catch (error) { if (error.status !== 404) throw error; }
        }
        if (!r.uploaded) {
          if (!r.file) throw Error('Datei bitte erneut auswählen.');
          const data = new FormData(); data.append('image', r.file); data.append('token', r.token);
          r.uncertain = true; persist();
          const result = await api(root + '/prepare', {method:'POST', body:data});
          Object.assign(r, result, {uploaded:true, uncertain:false}); persist();
        }
        let polls = 0;
        while (r.status === 'queued' && polls++ < 200) {
          r.message = 'Lokale Bilderkennung läuft …'; render();
          await new Promise(resolve => setTimeout(resolve, 3000));
          Object.assign(r, await api(root + '/' + r.token)); persist();
        }
        if (r.status === 'queued') throw Error('Erkennung dauert noch an. Mit „Fotos hochladen & erkennen“ später fortsetzen.');
      } catch (error) {
        r.message = error.name === 'AbortError' ? 'Verbindung unterbrochen. Erneut versuchen; bereits gespeicherte Bilder bleiben erhalten.' : error.message;
        failure = true;
      }
      render();
    }
    running = false; start.disabled = false; files.disabled = false;
    message.textContent = failure ? 'Einige Fotos sind noch nicht bereit. Fertige Bilder können geprüft und gespeichert werden; andere lassen sich erneut versuchen.' : 'Alle Fotos vorbereitet. Vorschläge prüfen und gemeinsam speichern.';
    render(); persist();
  }
  files.addEventListener('change', () => {
    if (running) return;
    const chosen = Array.from(files.files);
    const match = file => rows.find(r => r.status !== 'committed' && r.sourceName === file.name && r.size === file.size && r.modified === file.lastModified);
    const extra = chosen.filter(file => !match(file));
    if (rows.filter(r => r.status !== 'committed').length + extra.length > 20) { message.textContent = 'Bitte höchstens 20 Fotos auf einmal vorbereiten. Vorhandene Vorschläge bleiben erhalten.'; files.value = ''; return; }
    rows = rows.filter(r => { if (r.status === 'committed' && r.preview) URL.revokeObjectURL(r.preview); return r.status !== 'committed'; });
    chosen.forEach(file => {
      const old = match(file);
      if (old) { old.file = file; return; }
      rows.push({file, token:uid(), title:file.name.replace(/\.[^.]+$/, ''), status:'new', selected:true, sourceName:file.name, size:file.size, modified:file.lastModified, preview:URL.createObjectURL(file)});
    });
    persist(); render(); message.textContent = rows.length + ' Fotos ausgewählt. Vorhandene Vorschläge bleiben erhalten.';
  });
  form.addEventListener('submit', event => { event.preventDefault(); if (!rows.length) { message.textContent = 'Bitte zuerst Fotos auswählen.'; return; } process(); });
  save.addEventListener('click', async () => {
    if (running) return;
    const selected = rows.filter(r => r.selected !== false && r.status === 'ready');
    if (!selected.length) { message.textContent = 'Bitte mindestens ein fertiges Foto auswählen.'; return; }
    if (selected.some(r => !r.title?.trim() || !categories.includes(r.category))) { message.textContent = 'Bitte für jedes ausgewählte Foto Bildtitel und Kategorie prüfen.'; return; }
    running = true; save.disabled = true; start.disabled = true; files.disabled = true; render();
    try {
      const result = await api(root + '/commit', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({batch, items:selected.map(({token,title,category,description}) => ({token,title,category,description}))})});
      selected.forEach(r => { r.status = 'committed'; r.message = 'Gespeichert.'; }); persist(); render();
      message.textContent = result.count + ' Fotos gespeichert. Sie stehen jetzt für die automatische Angebotsauswahl bereit.';
      const link = node('a', 'Referenzbibliothek öffnen', 'btn light'); link.href = form.dataset.library; message.append(document.createElement('br'), link);
    } catch (error) { message.textContent = error.name === 'AbortError' ? 'Antwort ausgeblieben. Speichern erneut versuchen; es werden keine doppelten Bilder angelegt.' : error.message; }
    finally { running = false; start.disabled = false; files.disabled = false; render(); }
  });
  try {
    const stored = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
    if (stored?.rows?.length) { batch = stored.batch; rows = stored.rows; render(); message.textContent = 'Vorbereitete Fotos wiederhergestellt. Angaben prüfen oder Erkennung fortsetzen. Noch nicht hochgeladene Dateien bitte erneut auswählen.'; }
  } catch (_) {}
})();
