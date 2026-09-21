from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'ftst_angebotsdesigner/static/FTST-Technikeraufnahme-Ajax.pdf'
OUT.parent.mkdir(parents=True, exist_ok=True)
LOGO = ROOT / 'ftst_angebotsdesigner/assets/branding/FTST-Registered-Original.jpg'
c = canvas.Canvas(str(OUT), pagesize=A4)
c.setTitle('FT Sicherheitstechnik - Technikeraufnahme Ajax')
c.setAuthor('FT Sicherheitstechnik')
W,H=A4
red=HexColor('#cf1020'); ink=HexColor('#172126'); grey=HexColor('#657078'); line=HexColor('#ccd2d6')
fields=[]
def text(x,y,s,size=10,bold=False,color=ink):
    c.setFillColor(color); c.setFont('Helvetica-Bold' if bold else 'Helvetica',size); c.drawString(x,y,s)
def field(name,x,y,w,h=24,label=None,multi=False):
    if label: text(x,y+h+5,label,9,True)
    c.acroForm.textfield(name=name,tooltip=label or name,x=x,y=y,width=w,height=h,
        fontName='Helvetica',fontSize=10,textColor=ink,borderColor=line,fillColor=white,
        borderWidth=.6,forceBorder=True,fieldFlags='multiline' if multi else '',maxlen=800 if multi else 160)
    fields.append(name)
def check(name,x,y,label):
    c.acroForm.checkbox(name=name,tooltip=label,x=x,y=y,size=11,borderWidth=.7,
        borderColor=grey,fillColor=white,textColor=ink,buttonStyle='check',forceBorder=True)
    text(x+17,y+2,label,9); fields.append(name)
def section(y,n,title):
    text(36,y,n,11,True,red); text(61,y,title,12,True)
def header(page,title,sub):
    # Use the same original-logo viewport as the app, without modifying the image.
    scale=300/945
    c.saveState()
    clip=c.beginPath(); clip.rect(36,H-76,300,180*scale); c.clipPath(clip,stroke=0)
    c.drawImage(str(LOGO),36-40*scale,H-76-590*scale,width=1000*scale,height=1000*scale)
    c.restoreState()
    text(447,H-44,'TECHNIKERAUFNAHME',8,True,grey)
    text(447,H-58,'AJAX / VORLAGE 01',8,False,grey)
    c.setStrokeColor(line); c.line(36,H-89,W-36,H-89)
    text(36,H-119,title,23,True)
    text(36,H-139,sub,9,False,grey)
    c.setStrokeColor(line); c.line(36,35,W-36,35)
    text(36,22,'FT Sicherheitstechnik | Aufnahme zur Angebotsvorbereitung | 21.09.2026',8,False,grey)
    text(W-74,22,f'{page} / 2',8,False,grey)

header(1,'Bedarf vor Ort erfassen','Digital ausfüllen oder ausdrucken. Zahlen statt Strichlisten; Unbekanntes als offen kennzeichnen.')
section(674,'01','Kunde und Projekt')
field('projekt',36,632,260,label='Projekt / Kunde (vorläufiger Name genügt)')
field('datum',310,632,105,label='Datum')
field('techniker',429,632,130,label='Aufgenommen von')
field('objektadresse',36,583,523,label='Objektadresse: Straße, Hausnummer, PLZ und Ort (falls bekannt)')
field('kontakt',36,534,260,label='Ansprechpartner / Telefon oder E-Mail')
field('rechnung',310,534,249,label='Rechnungsempfänger / Billomat-Kundennr. (optional)')
section(503,'02','Grundlage der Planung')
text(36,481,'Zentrale bereits vorhanden?',9,True)
check('zentrale_ja',191,478,'Ja');check('zentrale_nein',245,478,'Nein');check('zentrale_offen',314,478,'Offen')
text(408,481,'Je Zeile nur eine Auswahl.',8,False,grey)
field('zentrale_modell',36,440,260,label='Vorhandene Zentrale / Modell (sonst offen)')
field('system_variante',310,440,249,label='Ajax-Serie / Funk oder Kabel / Farbe (sonst offen)')
section(408,'03','Neu benötigte Komponenten')
text(36,390,'Nur neu benötigte Stückzahlen eintragen. Leer = nicht erfasst; 0 = nicht benötigt.',9,False,grey)
ys=365
widths=[178,48,141,156]; xs=[36,214,262,403]
c.setFillColor(ink); c.rect(36,ys,523,22,fill=1,stroke=0)
for x,label in zip(xs,['Komponententyp','Anzahl','Raum / Einbauort','Variante / Hinweis']):text(x+5,ys+7,label,8,True,white)
types=['Bewegungsmelder innen','Bewegungsmelder außen','Tür-/Fensterkontakt','Innensirene','Außensirene','Bedienteil innen','Bedienteil außen','Zentrale (neu)','Funk-Repeater / Erweiterung','Weiteres Gerät / Zubehör']
for i,label in enumerate(types):
    y=ys-27*(i+1)
    text(41,y+10,label,9)
    c.setStrokeColor(line); c.line(36,y,559,y)
    for suffix,x,w in [('menge',214,48),('ort',262,141),('variante',403,156)]:
        field(f'position_{i+1}_{suffix}',x+3,y+3,w-6,21)
text(36,77,'Bei mehreren Räumen oder weiteren Geräten: Detailzeilen auf Seite 2 verwenden.',9,False,grey)
text(36,59,'Eine Bedarfsliste ersetzt keine Prüfung von Modell, Einsatzort und Systemkompatibilität.',8,False,grey)
c.showPage()

header(2,'Montage und Rückfragen','Ergänzungsblatt: dieselbe Projektbezeichnung wie auf Seite 1 verwenden.')
field('projekt_seite2',36,658,523,label='Projekt / Kunde')
section(628,'04','Details nach Raum / Einbauort')
text(36,611,'Diese Zeilen präzisieren Seite 1. Gleiche Geräte nicht erneut zur Gesamtmenge addieren.',9,False,grey)
c.setFillColor(ink);c.rect(36,579,523,22,fill=1,stroke=0)
for x,label in zip([36,171,346,394],['Raum / Einbauort','Gerät / konkrete Variante','Anzahl','Besonderheit / Foto-Nr.']):text(x+5,586,label,8,True,white)
for i in range(5):
    y=579-29*(i+1)
    for suffix,x,w in [('ort',36,135),('geraet',171,175),('menge',346,48),('hinweis',394,165)]:
        field(f'detail_{i+1}_{suffix}',x+3,y+3,w-6,23)
section(409,'05','Montage und Rahmenbedingungen')
field('montage',36,342,523,44,'Montageumfang / Untergrund / Höhe / Leitungswege / benötigtes Zubehör',True)
field('infrastruktur',36,274,523,44,'Strom / Internet / Mobilfunk / Zugang zum Objekt / besondere Bedingungen',True)
field('anfahrt',36,225,253,24,'Anfahrt / gewünschter Zeitraum (unverbindlich)')
field('offene_punkte',303,225,256,24,'Noch zu klären / Rückruf bei')
section(197,'06','Prüfen und zum Angebot weitergeben')
check('mengen_geprueft',36,171,'Mengen und Einbauorte geprüft')
check('varianten_offen',302,171,'Offene Varianten ausdrücklich markiert')
check('daten_nachreichen',36,150,'Kundendaten werden nachgereicht')
check('montage_geklaert',302,150,'Montageumfang erfasst oder offen markiert')
text(36,124,'So geht es in der App weiter',10,True)
for y,s in [(108,'1. Technikeraufnahme öffnen: Seite 1 fotografieren oder Angaben direkt eintragen.'),
            (94,'2. Ergebnis prüfen, Ergänzungen von Seite 2 eintragen und bestätigte Angaben übernehmen.'),
            (80,'3. Billomat-Kunde und genaue Artikel zuordnen; Mengen, Preise und Leistungsumfang prüfen.'),
            (66,'4. Angebots-PDF prüfen; erst danach den Entwurf bewusst an Billomat übergeben.')]:text(36,y,s,8.5)
text(36,47,'PDF-Dateiimport wird derzeit nicht unterstützt. Die Aufnahme kann zunächst ohne Kundendaten starten.',8,False,grey)
c.save()
r=PdfReader(OUT)
assert len(r.pages)==2
assert set(r.get_fields())==set(fields)
widgets=[a.get_object() for p in r.pages for a in p.get('/Annots',[]) if a.get_object().get('/Subtype')=='/Widget']
assert len(widgets)==len(fields)
assert all(a.get('/AP',{}).get('/N') for a in widgets)
print(f'{OUT}: {len(r.pages)} pages, {len(fields)} interactive fields')
