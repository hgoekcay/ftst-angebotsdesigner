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
  let rows = [], running = false, saving = false, pendingCommit = null, order = '';
  let batch = crypto.randomUUID().replaceAll('-', '');
  const cards = new Map();
  const uid = () => crypto.randomUUID().replaceAll('-', '');
  const persist = () => { try { sessionStorage.setItem(storageKey, JSON.stringify({batch, pendingCommit, rows: rows.map(({token, title, category, description, dirty, status, selected, uploaded, uncertain, sourceName, size, modified}) => ({token, title, category, description, dirty, status, selected, uploaded, uncertain, sourceName, size, modified}))})); } catch (_) {} };
  const node = (tag, text, className) => { const n = document.createElement(tag); if (text) n.textContent = text; if (className) n.className = className; return n; };
  const pending = r => pendingCommit?.items.some(item => item.token === r.token);
  const locked = r => saving || pending(r) || r.status === 'committed';
  const usable = r => r.uploaded && ['ready', 'queued'].includes(r.status);
  function merge(r, result) {
    if (r.status === 'committed') return;
    r.dirty ||= {};
    for (const key of ['title', 'category', 'description']) if (!r.dirty[key] && typeof result[key] === 'string') r[key] = result[key];
    for (const key of ['status', 'message']) if (typeof result[key] === 'string') r[key] = result[key];
  }
  async function api(url, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 60000);
    try {
      const response = await fetch(url, {...options, credentials: 'same-origin', signal: controller.signal});
      const json = (response.headers.get('Content-Type') || '').includes('application/json');
      let data = null;
      if (json) { try { data = await response.json(); } catch (_) {} }
      if (!response.ok) {
        let text = typeof data?.error === 'string' ? data.error.slice(0, 500) : '';
        if (response.status === 401 || response.status === 403) text = 'Bitte FTST Angebote in Home Assistant neu öffnen.';
        if (!text && response.status === 404) text = 'Upload noch nicht auf dem Server. Bitte ursprüngliche Datei erneut auswählen.';
        if (!text && response.status === 413) text = 'Foto zu groß: höchstens 12 MB pro Datei.';
        if (!text) text = 'Vorgang nicht abgeschlossen (HTTP ' + response.status + '). Bitte erneut versuchen.';
        const error = Error(text); error.status = response.status;
        error.definitive = [400,401,403,404,409,413,415,422].includes(response.status);
        throw error;
      }
      if (!json || !data) throw Error('Anmeldung oder Verbindung prüfen und erneut versuchen.');
      return data;
    } finally { clearTimeout(timer); }
  }
  function cardFor(r) {
    if (cards.has(r.token)) return cards.get(r.token);
    const card = node('article', '', 'card photo-review-card');
    const image = node('img'); image.className = 'material-preview'; card.append(image);
    const checkLabel = node('label', ' Dieses Foto übernehmen');
    const check = node('input'); check.type = 'checkbox'; check.style.width = 'auto';
    check.addEventListener('change', () => { if (locked(r)) return; r.selected = check.checked; persist(); }); checkLabel.prepend(check); card.append(checkLabel);
    const controls = {title:node('input'), category:node('select'), description:node('textarea')};
    controls.title.maxLength = 200; controls.description.maxLength = 2000;
    controls.category.append(new Option('Bitte zuordnen', '')); categories.forEach(c => controls.category.append(new Option(c, c)));
    const labels = {};
    for (const [key, label] of [['title','Bildtitel'],['category','Angebotsart'],['description','Beschreibung']]) {
      const control = controls[key], lab = node('label', label); labels[key] = lab;
      control.addEventListener('input', () => {
        if (locked(r)) return;
        r[key] = control.value; r.dirty ||= {}; r.dirty[key] = true; persist();
      });
      card.append(lab, control);
    }
    const remove = node('button', 'Aus Auswahl entfernen', 'btn light'); remove.type = 'button';
    remove.addEventListener('click', () => {
      if (running || locked(r)) return;
      rows = rows.filter(row => row !== r);
      if (r.preview) URL.revokeObjectURL(r.preview);
      files.value = ''; persist(); render();
      message.textContent = 'Foto aus dieser Auswahl entfernt. Gespeicherte Bibliotheksfotos bleiben erhalten.';
    });
    card.append(remove);
    const status = node('p'); status.setAttribute('role', 'status'); card.append(status);
    const result = {card,image,check,controls,labels,remove,status};
    cards.set(r.token, result);
    return result;
  }
  function render() {
    const visible = [];
    rows.forEach((r, index) => {
      const c = cardFor(r); visible.push(c.card);
      c.image.alt = r.title || ('Foto ' + (index + 1));
      const src = r.preview || root + '/' + r.token + '/preview';
      if (c.image.src !== src) c.image.src = src;
      c.check.checked = r.selected !== false; c.check.disabled = !!locked(r);
      for (const [key, control] of Object.entries(c.controls)) {
        const id = 'photo-' + index + '-' + key; control.id = id; c.labels[key].htmlFor = id;
        if (control.value !== (r[key] || '')) control.value = r[key] || '';
        control.disabled = !!locked(r);
      }
      c.remove.hidden = r.status === 'committed'; c.remove.disabled = running || !!locked(r);
      c.status.textContent = pending(r) ? 'Speichern noch nicht bestätigt. Bitte mit denselben Angaben erneut versuchen.' :
        r.status === 'committed' ? 'Gespeichert.' : r.message || 'Jedes Foto kann bereits vor der Erkennung beschrieben werden.';
    });
    const next = rows.map(r => r.token).join(',');
    if (next !== order) { list.replaceChildren(...visible); order = next; }
    save.hidden = !pendingCommit && !rows.some(usable); save.disabled = saving;
    start.disabled = running || saving || !!pendingCommit; files.disabled = running || saving || !!pendingCommit;
  }
  async function prepare(r) {
    if (r.status === 'committed' || r.uploaded) return;
    if (r.uncertain) {
      try { merge(r, await api(root + '/' + r.token)); r.uploaded = true; r.uncertain = false; persist(); return; }
      catch (error) { if (error.status !== 404) throw error; }
    }
    if (!r.file) throw Error('Datei bitte erneut auswählen.');
    const data = new FormData(); data.append('image', r.file); data.append('token', r.token);
    r.uncertain = true; persist();
    merge(r, await api(root + '/prepare', {method:'POST', body:data}));
    r.uploaded = true; r.uncertain = false; persist();
  }
  async function process() {
    if (running || saving || pendingCommit) return;
    running = true; render(); let failure = false;
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      message.textContent = 'Foto ' + (i + 1) + ' von ' + rows.length + ' hochladen …';
      try { await prepare(r); } catch (error) {
        r.message = error.name === 'AbortError' ? 'Verbindung unterbrochen. Erneut versuchen; vorhandene Fotos bleiben erhalten.' : error.message; failure = true;
      }
      render();
    }
    await Promise.all(rows.filter(r => r.uploaded && r.status === 'queued').map(async r => {
      try {
        let polls = 0;
        while (r.status === 'queued' && polls++ < 200) {
          await new Promise(resolve => setTimeout(resolve, 3000));
          if (r.status !== 'queued') break;
          merge(r, await api(root + '/' + r.token)); persist(); render();
        }
        if (r.status === 'queued') { r.message = 'Erkennung dauert noch. Angaben selbst ergänzen und geprüfte Fotos speichern oder später fortsetzen.'; failure = true; }
      } catch (error) { if (r.status !== 'committed') { r.message = error.message; failure = true; } }
    }));
    running = false;
    if (!saving && !pendingCommit) message.textContent = rows.every(r => r.status === 'committed') ? 'Alle ausgewählten Fotos sind gespeichert.' :
      failure ? 'Einige Fotos sind noch nicht erkannt. Titel, Kategorie und Beschreibung können Sie je Foto selbst bearbeiten.' :
      'Alle Fotos vorbereitet. Angaben je Foto prüfen und gemeinsam speichern.';
    render(); persist();
  }
  files.addEventListener('change', () => {
    if (running || saving || pendingCommit) return;
    const chosen = Array.from(files.files);
    const match = file => rows.find(r => r.status !== 'committed' && r.sourceName === file.name && r.size === file.size && r.modified === file.lastModified);
    const extra = chosen.filter(file => !match(file));
    if (rows.filter(r => r.status !== 'committed').length + extra.length > 20) { message.textContent = 'Bitte höchstens 20 Fotos auf einmal vorbereiten. Vorhandene Angaben bleiben erhalten.'; files.value = ''; return; }
    rows = rows.filter(r => { if (r.status === 'committed' && r.preview) URL.revokeObjectURL(r.preview); return r.status !== 'committed'; });
    chosen.forEach(file => {
      const old = match(file); if (old) { old.file = file; return; }
      rows.push({file, token:uid(), title:file.name.replace(/\.[^.]+$/, ''), dirty:{}, status:'new', selected:true, sourceName:file.name, size:file.size, modified:file.lastModified, preview:URL.createObjectURL(file)});
    });
    persist(); render(); message.textContent = rows.length + ' Fotos ausgewählt. Jedes Foto hat eigene bearbeitbare Angaben.';
  });
  form.addEventListener('submit', event => { event.preventDefault(); if (!rows.length) { message.textContent = 'Bitte zuerst Fotos auswählen.'; return; } process(); });
  save.addEventListener('click', async () => {
    if (saving) return;
    if (!pendingCommit) {
      const selected = rows.filter(r => r.selected !== false && usable(r));
      if (!selected.length) { message.textContent = 'Bitte mindestens ein hochgeladenes Foto auswählen.'; return; }
      if (selected.some(r => !r.title?.trim() || !categories.includes(r.category))) { message.textContent = 'Bitte für jedes ausgewählte Foto Bildtitel und Kategorie prüfen.'; return; }
      pendingCommit = {batch, items:selected.map(({token,title,category,description,status}) => ({token,title:title.trim(),category,description:(description || '').trim(), ...(status === 'queued' ? {manual:true} : {})}))};
      persist();
    }
    saving = true; render();
    try {
      const sent = pendingCommit;
      const result = await api(root + '/commit', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(sent)});
      if (result.count !== sent.items.length) throw Error('Speicherung nicht eindeutig bestätigt. Bitte denselben Vorgang erneut versuchen.');
      for (const item of sent.items) {
        const r = rows.find(row => row.token === item.token);
        if (r) { Object.assign(r, {title:item.title, category:item.category, description:item.description, status:'committed', message:'Gespeichert.'}); }
      }
      pendingCommit = null; batch = uid(); persist();
      message.textContent = result.count + ' Fotos gespeichert. Sie stehen jetzt für die automatische Angebotsauswahl bereit.';
      const link = node('a', 'Referenzbibliothek öffnen', 'btn light'); link.href = form.dataset.library; message.append(document.createElement('br'), link);
    } catch (error) {
      if (error.definitive) { pendingCommit = null; batch = uid(); persist(); }
      message.textContent = error.name === 'AbortError' ? 'Antwort ausgeblieben. Speichern mit denselben Angaben erneut versuchen; keine doppelten Bilder.' : error.message;
    } finally { saving = false; render(); }
  });
  try {
    const stored = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
    if (stored?.rows?.length) {
      batch = stored.batch; pendingCommit = stored.pendingCommit || null; rows = stored.rows;
      for (const r of rows) {
        r.uploaded = r.uploaded || ['ready','committed','queued'].includes(r.status);
        r.dirty ||= {title:!!r.title && r.title !== r.sourceName?.replace(/\.[^.]+$/, ''), category:!!r.category, description:!!r.description};
      }
      render(); message.textContent = pendingCommit ? 'Speicherung noch nicht bestätigt. Bitte mit denselben Angaben erneut speichern.' :
        'Vorbereitete Fotos wiederhergestellt. Jedes Foto kann einzeln beschrieben werden. Fehlende Originaldateien bitte erneut auswählen.';
    }
  } catch (_) {}
})();
