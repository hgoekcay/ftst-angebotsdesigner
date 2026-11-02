'use strict';
const byId = id => document.getElementById(id);
const form = document.querySelector('form');
const notice = byId('notice');
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let csrf, busy = false, conversation = 0, listening, speaking, timeout;
const voiceSelect = byId('voiceSelect');
const previewButton = byId('previewVoice');
const voiceKey = 'ftst-hermes.voice.v1';
let preferredVoice = '', voices = [], preview;
try { preferredVoice = localStorage.getItem(voiceKey) || ''; } catch {}

function voiceId(voice) {
  return JSON.stringify([voice.voiceURI || '', voice.name, voice.lang]);
}
function voiceRank(voice) {
  return (/natural|neural|natürlich|premium|enhanced/i.test(voice.name) ? 8 : 0)
    + (/^de[-_]de$/i.test(voice.lang) ? 4 : 0)
    + (voice.localService ? 2 : 0) + (voice.default ? 1 : 0);
}
function chosenVoice() {
  return voices.find(v => voiceId(v) === preferredVoice) || voices[0];
}
function refreshVoices() {
  voices = speechSynthesis.getVoices().filter(v => /^de(?:[-_]|$)/i.test(v.lang))
    .sort((a,b) => voiceRank(b) - voiceRank(a) || a.name.localeCompare(b.name, 'de'));
  const automatic = new Option('Automatische Auswahl', '');
  voiceSelect.replaceChildren(automatic);
  for (const voice of voices) {
    voiceSelect.add(new Option(voice.name + (voice.localService ? ' · Gerät' : ' · Online'), voiceId(voice)));
  }
  voiceSelect.value = voices.some(v => voiceId(v) === preferredVoice) ? preferredVoice : '';
  const selected = chosenVoice();
  byId('voiceInfo').textContent = selected
    ? 'Aktive Stimme: ' + selected.name + '. ' + (selected.localService
      ? 'Die Sprachausgabe läuft auf deinem Gerät.'
      : 'Antworttexte werden zur Sprachausgabe vom Sprachanbieter verarbeitet.')
    : 'Dein Browser verwendet seine Standardstimme für Deutsch.';
}
function utterance(text) {
  const speech = new SpeechSynthesisUtterance(text);
  const selected = chosenVoice();
  if (selected) speech.voice = selected;
  speech.lang = selected?.lang || 'de-DE';
  return speech;
}
function cancelPreview() {
  if (!preview) return;
  preview.onend = preview.onerror = null;
  preview = null;
  speechSynthesis.cancel();
  previewButton.textContent = 'Stimme anhören';
}
voiceSelect.onchange = () => {
  cancelPreview();
  preferredVoice = voiceSelect.value;
  try { localStorage.setItem(voiceKey, preferredVoice); } catch {}
  refreshVoices();
};
previewButton.onclick = () => {
  if (conversation || !window.speechSynthesis) return;
  if (preview) return cancelPreview();
  preview = utterance('Hallo, hier ist Hermes. Was steht heute bei dir an?');
  preview.onend = preview.onerror = () => {
    preview = null;
    previewButton.textContent = 'Stimme anhören';
  };
  previewButton.textContent = 'Hörprobe beenden';
  speechSynthesis.speak(preview);
};
function line(who, text) {
  const p = document.createElement('p');
  p.textContent = who + ' · ' + text;
  byId('log').append(p);
}
function stop(message) {
  conversation = 0;
  cancelPreview();
  previewButton.disabled = false;
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
      speaking = utterance(data.reply);
      speaking.onend = () => { if (conversation === id) { speaking = null; hear(id); } };
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
  cancelPreview();
  previewButton.disabled = true;
  conversation = Date.now();
  byId('voice').textContent = 'Gespräch beenden';
  timeout = setTimeout(() => stop('Gespräch nach zehn Minuten beendet.'), 600000);
  hear(conversation);
};
window.addEventListener('pagehide', () => stop(''));
document.addEventListener('visibilitychange', () => { if (document.hidden && conversation) stop('Gespräch pausiert.'); });
fetch('state').then(r => { if (!r.ok) throw Error(); return r.json(); }).then(s => {
  csrf = s.csrf; byId('tasks').textContent = s.tasks ? 'ATLAS-Aufgabenwerkzeuge konfiguriert.' : 'ATLAS-Aufgabenwerkzeuge noch nicht konfiguriert.';
  if (window.speechSynthesis) {
    refreshVoices();
    speechSynthesis.addEventListener('voiceschanged', refreshVoices);
    byId('voiceSettings').hidden = false;
  }
  if (Recognition && window.speechSynthesis) { byId('voice').hidden = false; byId('voiceHint').hidden = false; }
}).catch(() => { notice.textContent = 'Zugriff prüfen und die Seite neu laden.'; });
