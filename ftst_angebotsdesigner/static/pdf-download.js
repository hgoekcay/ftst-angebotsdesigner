/* Fetch within the authenticated Ingress document before handing off a file. */
document.addEventListener('click', async (event) => {
  const link = event.target.closest('a[data-pdf]');
  if (!link) return;
  event.preventDefault();
  if (link.dataset.loading) return;
  link.dataset.loading = '1';
  const box = document.createElement('div');
  box.className = 'card';
  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  status.textContent = 'PDF wird vorbereitet …';
  box.append(status);
  link.after(box);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 90000);
  try {
    const response = await fetch(link.href, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
    if (response.status === 401 || response.status === 403) {
      throw Error('Die Home-Assistant-Anmeldung ist abgelaufen. FTST Angebote über die Home-Assistant-Seitenleiste neu öffnen und erneut versuchen.');
    }
    if (!response.ok) throw Error('PDF konnte nicht erstellt werden (HTTP ' + response.status + '). Bitte erneut versuchen.');
    if (!(response.headers.get('Content-Type') || '').toLowerCase().includes('application/pdf')) {
      throw Error('Der Server hat keine PDF-Datei geliefert. Bitte FTST Angebote in Home Assistant neu öffnen.');
    }
    const blob = await response.blob();
    if (await blob.slice(0, 5).text() !== '%PDF-') throw Error('Die Antwort ist keine gültige PDF-Datei. Es wurde nichts gespeichert.');
    const filename = link.dataset.pdf || 'FTST-Angebot.pdf';
    const url = URL.createObjectURL(blob);
    const save = document.createElement('a');
    save.className = 'btn dark';
    save.href = url;
    save.download = filename;
    save.textContent = 'PDF speichern';
    box.append(save);
    const file = new File([blob], filename, {type: 'application/pdf'});
    if (navigator.share && navigator.canShare && navigator.canShare({files: [file]})) {
      const share = document.createElement('button');
      share.type = 'button';
      share.className = 'btn light';
      share.textContent = 'PDF teilen / in Dateien sichern';
      share.addEventListener('click', async () => {
        try { await navigator.share({files: [file], title: filename}); }
        catch (error) { if (error.name !== 'AbortError') status.textContent = 'Teilen nicht verfügbar. Bitte PDF speichern verwenden.'; }
      });
      box.append(share);
    }
    status.textContent = 'PDF ist bereit. Jetzt speichern oder über das Teilen-Menü in Dateien sichern.';
    link.hidden = true;
    link.style.display = 'none';
    window.addEventListener('pagehide', (event) => { if (!event.persisted) URL.revokeObjectURL(url); });
  } catch (error) {
    status.textContent = error.name === 'AbortError' ? 'PDF-Abruf hat zu lange gedauert. Bitte erneut versuchen.' : error.message;
  } finally {
    clearTimeout(timer);
    delete link.dataset.loading;
  }
});
