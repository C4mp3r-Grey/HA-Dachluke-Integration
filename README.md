# Dachluke Badentlüftung

Home-Assistant-Integration für eine motorisierte Dachluke (Homematic IP **HmIP-BROLL**) zur Badentlüftung. Sie ersetzt den Blueprint `dachluke_steuerung.yaml` und bringt drei Dinge in einem Paket:

1. **Steuerung**: öffnet nach dem Duschen, schließt wieder, berücksichtigt Wetter, Frost, Heizung, Alarm und Tasten.
2. **Analyse**: zählt und protokolliert jede Öffnung, jedes Schließen und jede Dusche, auch wenn die Luke dabei nicht geöffnet hat, jeweils mit Grund.
3. **Seitenleisten-Seite „Dachluke“**: zeigt Status, Zähler, Verlauf und Protokoll. Sie erzeugt außerdem auf Knopfdruck eine Dashboard-YAML mit deinen echten Entity-IDs.

Alles wird in der Oberfläche eingerichtet. Helfer, Statistik-Sensoren oder YAML-Pakete brauchst du nicht mehr.

---

## Installation über HACS

1. HACS → ⋮ → **Benutzerdefinierte Repositories** → URL dieses Repositorys, Typ **Integration**.
2. „Dachluke Badentlüftung“ herunterladen und Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Dachluke Badentlüftung**.
4. Cover, Positionssensor (Kanal 3) und Hygrometer wählen, optional Wetter und Lampen.
5. Danach unter **Konfigurieren** die weiteren Bereiche einstellen: Heizung, Tasten, Alarm, Benachrichtigungen.

Ohne HACS kopierst du den Ordner `custom_components/dachluke` nach `/config/custom_components/` und startest neu.

### Positionssensor Kanal 3 freischalten

Homematic(IP) Local → HmIP-BROLL öffnen → **Unignore Parameters** → Kanal 3 → `LEVEL` → Neustart. Die Integration erwartet die Position in **0–100 %**.

### Zwei Feuchtesensoren (empfohlen)

- **Feuchte an der Dusche:** ein schnell reagierender Sensor nahe der Dusche. Er erkennt Beginn und Ende des Duschens und darf dabei auch auf 100 % gehen.
- **Raumfeuchte (optional):** zum Beispiel das Wandthermostat, abseits der Dusche. Ist er eingetragen, entscheiden Raumfeuchte und Raumtemperatur über das Schließen, die Stagnation und das zweite Nachlüften. Ohne eigenen Raumtemperatur-Sensor wird die Ist-Temperatur des Thermostats verwendet. Statt eines Feuchtesensors kann auch direkt das Thermostat (`climate`) gewählt werden. Dann liest die Integration dessen Attribut `current_humidity`.

Protokoll, Bilanz und Verlauf zeigen beide Sensoren nebeneinander, damit du sie vergleichen kannst.

### Umstieg vom Blueprint

1. Integration einrichten. Unter Konfigurieren dieselben Entitäten und Werte wie im Blueprint eintragen.
2. Die alte Blueprint-Automation **deaktivieren**, nicht löschen. Sonst steuern zwei Automationen die Luke.
3. Läuft alles ein paar Tage stabil, kannst du die alte Automation, die Helfer (`input_boolean.dachluke_pause`, `input_boolean.dachluke_deaktiviert`, `timer.dachluke_*`, `input_text.dachluke_status`) und den Statistik-Sensor entfernen.

---

## Was anders ist als im Blueprint

| Thema | Blueprint 0.7.5 | Integration |
|---|---|---|
| Zweiter gleicher Tastendruck | wurde nicht erkannt (Attribut-Trigger) | jeder Druck wird erkannt |
| Öffnen per Dashboard, Alexa, CCU | kein Timer, Luke blieb offen | jede Öffnung bekommt einen Timer |
| Schließen | feste 65 % oder Taupunkt | sobald die Feuchte wieder beim *Ausgangswert vor dem Duschen* liegt: mit Temperatursensor nach **absoluter** Feuchte (+1 g/m³), sonst nach relativer (+3 %). Feste Schwelle und Taupunkt gibt es optional zusätzlich |
| Außenwerte & Regen | Met.no-Zustand „rainy“ (Vorhersagesymbol) | optional **DWD-Messwerte** der nächsten Station über [Bright Sky](https://brightsky.dev/) (frei, ohne Schlüssel; Koordinaten auf ~1 km gerundet) und/oder ein **Regensensor** in mm. Dann zählt gemessener Regen, nicht das Symbol. Hagel/Sturm weiter aus der Wetter-Entität |
| Erhöhte Ausgangsfeuchte | – | war der Raum vor dem Duschen schon feuchter als üblich, gilt die **übliche Raumfeuchte** als Ziel (Median aus Ruhephasen der letzten 3 Tage). Untergrenze ist die absolute Feuchte draußen + 0,5 g/m³ |
| Zwei Sensoren beim Schließen | – | mit Raumsensor schließt die Luke erst, wenn **beide** passen: Raumluft wieder nahe am Ziel **und** die feuchte Luft über der Dusche verzogen. Stagnation erst, wenn **kein** Sensor mehr fällt |
| Nachlüftzeit | harte Grenze | weich: fällt die Feuchte noch, wird in 5-min-Schritten verlängert (bis Obergrenze oder Stagnation) |
| Trocknung stagniert | Luke blieb bis Zeitablauf offen | schließt, wenn die Feuchte nach dem Duschen 10 min lang um weniger als 1 % fällt (z. B. bei feuchter Außenluft) |
| Maximale Öffnungsdauer | ab Öffnen | ab **Duschende** (Feuchte fällt um 3 % vom Höchstwert). Während des Duschens bleibt die Luke offen, Obergrenze 90 min |
| Handöffnung zum Stoßlüften | wurde beim nächsten Feuchtewert zugemacht | läuft die eingestellte Zeit (Standard 15 min). Duscht jemand währenddessen, übernimmt die Automatik |
| Licht | Pflicht zum Öffnen | optional (Standard: aus) |
| Pause nach Neustart | konnte hängen bleiben | Pause und Timer überstehen Neustarts |
| Alarm | schaltete Automatik dauerhaft ab | sperrt nur, solange der Alarm aktiv ist |
| Heizung nach dem Lüften | feste 22 °C, blieb bei unbemerktem Schließen auf 15 °C | stellt den vorherigen Sollwert wieder her, bei *jedem* Schließen |
| Zweites Nachlüften | nur nach Zeitablauf | nach Zeitablauf und nach Schließen wegen Feuchte |
| Feuchte-Anstieg | eigener Statistik-Sensor nötig | wird intern berechnet, robust bei seltenen Messwerten |
| Warteschlange | konnte Ereignisse stumm verwerfen | jedes Ereignis wird verarbeitet |

## Tasten

| Taste | Kurz | Lang |
|---|---|---|
| Öffnen (Gerät) | Pause aufheben | Automatik aktivieren |
| Schließen (Gerät) | Pause | Automatik deaktivieren |
| Fernbedienung | wie oben, öffnet bzw. schließt zusätzlich die Luke | wie oben |

Erkannt werden die Ereignistypen `press_short` und `press_long_release` bzw. `press_long_start` der Homematic(IP)-Local-Event-Entitäten.

## Entitäten

- `sensor.…_status`: Bereit, Lüftet (Automatik/von Hand), Nachlüften, Pause, Deaktiviert, Gesperrt (Alarm/Wetter), Sensor fehlt. Das Attribut `hindernisse_oeffnen` nennt, warum gerade nicht geöffnet würde.
- `sensor.…_feuchte_anstieg_5_min`, `…_ausgangsfeuchte`, `…_luftung_endet`, `…_dauer_letzte_luftung`, `…_letztes_ereignis`
- Zähler (Diagnose): automatisch und von Hand geöffnet; geschlossen wegen Feuchte, Zeit, stagnierender Trocknung, von Hand, Wetter/Alarm; Duschen erkannt; Duschen ohne Öffnen; Sensorausfälle
- `binary_sensor.…_luke_offen`, `switch.…_automatik`, `switch.…_pause`
- Tasten: **Jetzt lüften** (öffnet auf die passende Weite, wetter- und alarmbewusst, gilt als Handöffnung), **Lüftung beenden** (schließt mit Pause), **Analyse zurücksetzen**

Die genauen Entity-IDs hängen von der Sprache bei der Einrichtung ab. Die Seitenleisten-Seite zeigt sie und baut daraus die Dashboard-YAML.

## Analyse auswerten

Auf der Seite **Dachluke** unter *Protokoll* → **Als CSV kopieren**. Jede Zeile enthält Zeit, Ereignis und Details, zum Beispiel:

```
2026-11-08T07:14:02+01:00;DUSCHE_VERPASST;"Dusche ohne Öffnen: Steigung max. 6.3 < Schwelle 8; Licht war aus"
```

Wichtige Ereignisse für die Auswertung:

| Ereignis | Inhalt |
|---|---|
| `START`, `EINSTELLUNGEN` | Version und wichtige Einstellungen bei jedem Start, geänderte Werte mit alt → neu |
| `AUTO_AUF` | Öffnungsweite **mit Grund** (normal, eingeschränktes Wetter, Frost, gesperrt), Auslöser, Ausgangsfeuchte, Beginn des Anstiegs, Umgebung |
| `HAND_AUF`, `HAND_ZU` | ob per Taste, Fernbedienung oder ohne erkannten Tastendruck |
| `ENDLAGE` | Position nach Stillstand der Luke und Zustand des Fensterkontakts |
| `DUSCHE_ENDE` | Höchstwert und **geschätzte Duschdauer** |
| `BILANZ` | je Lüftung: Grund, Dauer (davon nach Duschende), max. Öffnung, Höchstwert, Feuchte vorher/nachher, Umgebung |
| `WIDERSPRUCH` | Kontakt und Position passen nicht zusammen, erst gemeldet, wenn die Luke steht und es 30 s später noch gilt |

„Umgebung“ heißt: Feuchte innen (absolut, wenn Temperatur eingetragen), Wetter, Außentemperatur, Außenfeuchte, Taupunkt, Licht, Lüfter, Heizungsmodus und Sollwert.

Das Protokoll speichert die letzten 500 Einträge. Längere Zeiträume liefert der Verlauf von `sensor.…_letztes_ereignis` (Verlauf → Download).

## Grenzen

- Getestet mit der offiziellen Home-Assistant-Testumgebung (HA 2026.2.3) und automatisierten Abläufen, **nicht an echter Hardware**. Die ersten Tage bitte beobachten.
- Die Seitenleisten-Seite nutzt die offizielle Schnittstelle für eigene Panels (`panel_custom`). Sie ist kein bearbeitbares Lovelace-Dashboard. Dafür gibt es die erzeugte YAML.
- Der Lüfter wird beim Lüften eingeschaltet (abschaltbar) und danach nur ausgeschaltet, wenn die Integration ihn selbst eingeschaltet hat.

## Entwicklung

```
pip install pytest-homeassistant-custom-component home-assistant-frontend
pytest
```
