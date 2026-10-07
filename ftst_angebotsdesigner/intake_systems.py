"""Explicit technician system choices; no automatic product or quantity selection."""

SYSTEMS = {
    'alarm': ('Alarmanlage / Ajax', 'Ajax', 'Ajax',
              'Zentrale, Melder, Sirenen und Bedienteile nach Raum erfassen.', {}),
    'video': ('Videoüberwachung', '', 'Videoueberwachung',
              'Kamerastandorte, Innen/Außen, Blickbereiche, Aufzeichnung/Speicherdauer, Netzwerk und Strom erfassen.',
              {'camera': 'Kamera', 'recorder': 'Rekorder', 'disk': 'Festplatte', 'poe': 'PoE-Switch'}),
    'access': ('Zutrittssystem', '', 'Zutrittssysteme',
               'Türen, Leser, Zutrittsmedium, Nutzer/Berechtigungen, vorhandene Schlösser und Schnittstellen erfassen.',
               {'reader': 'Zutrittsleser', 'controller': 'Zutrittscontroller', 'credential': 'Transponder', 'relay': 'Relaismodul'}),
    'cylinder': ('Schließzylinder', '', 'Schliesszylinder',
                 'Je Tür Zylindermaße innen/außen, Bauform, Beschlag, Schließberechtigung und Besonderheiten erfassen.',
                 {'cylinder': 'Schließzylinder', 'key': 'Schlüssel', 'knob': 'Knaufzylinder'}),
    'intercom': ('Türsprechanlage', '', 'Tuersprechanlagen',
                'Eingänge, Wohneinheiten/Rufziele, Audio/Video, Innenstationen, Bus/IP, Leitungen und Türöffner erfassen.',
                {'outdoor': 'Außenstation', 'indoor': 'Innenstation', 'supply': 'Netzteil', 'opener': 'Türöffner', 'gateway': 'IP-Gateway'}),
}


def system_key(fields):
    return fields.get('system_type', 'alarm')


def profile(fields):
    return SYSTEMS.get(system_key(fields), SYSTEMS['alarm'])


def with_manufacturer(description, manufacturer):
    """Keep explicitly named preferred brands and service lines unchanged."""
    folded = description.casefold()
    if not manufacturer or any(brand in folded for brand in ('ajax', 'dahua', 'ftronics', 'falke')):
        return description
    if manufacturer.casefold() in folded or any(word in folded for word in ('montage', 'arbeitsstund', 'anfahrt', 'einweisung', 'installation', 'konfiguration')):
        return description
    return manufacturer + ' ' + description
