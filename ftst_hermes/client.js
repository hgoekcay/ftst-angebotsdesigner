'use strict';
const byId = id => document.getElementById(id);
const form = document.querySelector('form');
const notice = byId('notice');
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let csrf, busy = false, conversation = 0, listening, speaking, timeout;
function line(who, text) {
  const p = document.createElement('p');
  p.textContent = who + ' · ' + text;
  byId('log').append(p);
}
function stop(message) {
  conversation = 0;
  clearTimeout(timeout);
  if (listening) { listening.onend = null; listening.abort(); listening = null; }
  if (speaking) { speaking.onend = null; speechSynthesis.cancel(); speaking = null; }
  byId('voice').textContent = 'Sprachgespräch starten';
  notice.textContent = message;
}
function hear(id) {
  if (id !== conversation) return;
  try {
    const mic = new Recognition();
    listening = mic;
    mic.lang = 'de-DE';
    let words = '';
    mic.onresult = event => { words = event.results[0][0].transcript.trim(); };
    mic.onerror = event => {
      if (id === conversation && event.error !== 'no-speech') stop('Spracheingabe unterbrochen. Mikrofonfreigabe prüfen.');
    };
    mic.onend = () => {
      if (id !== conversation) return;
      listening = null;
      if (!words) return stop('Keine Sprache erkannt. Du kannst erneut starten.');
      if (/^(stopp?|gespräch beenden)[.!?]*$/i.test(words)) return stop('Gespräch beendet.');
      send(words, id);
    };
    notice.textContent = 'Ich höre zu.';
    mic.start();
  } catch { stop('Mikrofon konnte nicht gestartet werden.'); }
}
async function send(text, id = 0) {
  if (!csrf || busy || !text) return;
  busy = true; byId('send').disabled = true; byId('text').disabled = true;
  line('Du', text); notice.textContent = 'Hermes arbeitet …';
  try {
    const result = await fetch('turn', {method:'POST', headers:{'Content-Type':'application/json','X-FTST-CSRF':csrf}, body:JSON.stringify({message:text})});
    if (!result.ok) throw new Error('Auftrag nicht bestätigt. Bei Aufgaben vor einer Wiederholung die Liste prüfen.');
    const data = await result.json();
    line('Hermes', data.reply); notice.textContent = '';
    if (id && id === conversation) {
      speaking = new SpeechSynthesisUtterance(data.reply);
      speaking.lang = 'de-DE'; speaking.onend = () => { if (conversation === id) { speaking = null; hear(id); } };
      speaking.onerror = () => { if (conversation === id) stop('Sprachausgabe unterbrochen. Die Antwort steht im Gespräch.'); };
      speechSynthesis.speak(speaking); notice.textContent = 'Hermes spricht.';
    }
  } catch { stop('Antwort fehlt. Vor erneutem Senden die Aufgabenliste prüfen.'); }
  finally { busy = false; byId('send').disabled = false; byId('text').disabled = false; }
}
form.onsubmit = e => { e.preventDefault(); if (busy || !csrf) return; const text = byId('text').value.trim(); if (!text) return; if (conversation) stop(''); byId('text').value = ''; send(text); };
byId('voice').onclick = () => {
  if (conversation) return stop('Gespräch beendet.');
  if (!csrf || busy) return;
  conversation = Date.now();
  byId('voice').textContent = 'Gespräch beenden';
  timeout = setTimeout(() => stop('Gespräch nach zehn Minuten beendet.'), 600000);
  hear(conversation);
};
window.addEventListener('pagehide', () => stop(''));
document.addEventListener('visibilitychange', () => { if (document.hidden && conversation) stop('Gespräch pausiert.'); });
fetch('state').then(r => { if (!r.ok) throw Error(); return r.json(); }).then(s => {
  csrf = s.csrf; byId('tasks').textContent = s.tasks ? 'ATLAS-Aufgabenwerkzeuge konfiguriert.' : 'ATLAS-Aufgabenwerkzeuge noch nicht konfiguriert.';
  if (Recognition && window.speechSynthesis) { byId('voice').hidden = false; byId('voiceHint').hidden = false; }
}).catch(() => { notice.textContent = 'Zugriff prüfen und die Seite neu laden.'; });
