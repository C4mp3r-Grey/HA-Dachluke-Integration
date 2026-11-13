# Änderungen

Neue Versionen erscheinen in HACS als Update, sobald ein Release mit Tag `vX.Y.Z` existiert. Es entsteht über den Workflow `Release` (Actions → Release → Run workflow, Versionsnummer eingeben). Er legt Tag und Release nur an, wenn alle Prüfungen grün sind.

## 1.18.1 – 2026-11-13

- Behoben: Nach einem Schließbefehl der Integration meldete der HmIP-BROLL zuerst 0 % und dann noch einmal die alte Position 100 %. Das wurde als neue Handöffnung „außerhalb von HA“ gewertet (Protokoll 13.11. 13:49). Öffnungsmeldungen bis 60 s nach dem eigenen Schließen gelten jetzt als Nachläufer. Eine echte Wiederöffnung danach wird normal erkannt, innerhalb des Fensters übernimmt das Sicherheitsnetz sie nach wenigen Minuten.
- Manifest: Kategorien für HA 2026.11 (Lüfter und Lüftung, Jalousien und Vorhänge).

## 1.18.0 – 2026-11-09

- **Betriebsart „Wärme sparen“** (neue Auswahl-Entität *Betriebsart*, z. B. bei Heizungsausfall): Beim Duschen läuft nur der Lüfter (eigener Abzug nach draußen), die Luke öffnet erst nach dem Duschende, dann auf 100 % (Stoßlüften; Begrenzung bei Regen und Frost bleibt) für höchstens 10 min. Sie schließt früher bei Zielfeuchte oder sobald der Raum 1 K kälter ist als beim Öffnen. Keine Verlängerung, kein Weiterlüften bei trockener Außenluft, kein zweites Nachlüften, Handöffnung 10 min. Die Betriebsart übersteht Neustarts und lässt sich per Automation umschalten.
- Status-Attribute `betriebsart` und `wartet_auf_duschende`; Seitenleiste zeigt die Betriebsart, die Dashboard-Vorlage hat einen Wähler.
- „Automatik aus“ heißt ausdrücklich: Die Integration greift nicht ein (keine Übernahme, kein Zeitlimit), außer bei Sturm, Hagel oder Alarm.

## 1.17.1 – 2026-11-09

- Behoben: Bei ausgeschalteter Automatik übernahm sie trotzdem eine Handöffnung, sobald während der Öffnung geduscht wurde, und hätte die Luke dann nach Zeitablauf geschlossen (Protokoll 09.11., 07:44). Mit ausgeschalteter Automatik bleibt eine Handöffnung jetzt in jedem Fall ohne Zeitlimit offen.

## 1.17.0 – 2026-11-08

- **Weiterlüften bei trockener Außenluft** (neue Option, Standard an, unter *Lüften*): Steht die Feuchte nach dem Duschen, obwohl der Raum noch über der Schließgrenze liegt und die Außenluft mindestens 2 g/m³ trockener ist, schließt die Luke nicht mehr wegen „Trocknung stagniert“, sondern lüftet bis zur Schließgrenze, zur harten Obergrenze oder zum Auskühlschutz weiter. Anlass: Protokoll 06.11. 21:10 und 08.11. 17:34, beide Male stand die absolute Feuchte bei gleichbleibender Raumtemperatur deutlich über dem Ziel, danach wurde von Hand wieder geöffnet.
- Protokoll unterscheidet „Trocknung läuft“ und „Noch zu feucht, Trocknung langsam“.

## 1.16.2 – 2026-11-08

- Zweite Dusche während einer laufenden Lüftung (Feuchte steigt mehr als 5 min nach dem Duschende wieder) zählt als eigene Dusche. 1.16.1 hatte sie nicht mehr gezählt.
- Die harte Obergrenze zählt bei einer solchen zweiten Dusche ab deren Beginn statt ab dem ersten Öffnen (Protokoll 08.11.: nach 60 min geschlossen, 28 min nach Ende der zweiten Dusche).

## 1.16.1 – 2026-11-06

- Behoben: Ein erneuter Feuchte-Anstieg bei schon offener Luke wurde als eigene Dusche und als „Dusche ohne Öffnen“ gezählt (Protokoll 06.11., 17:34 und 20:44). Er wird jetzt nur protokolliert.
- Behoben: Steigt die Feuchte bis 5 min nach dem erkannten Duschende wieder, gilt das als dieselbe Dusche. Die geschätzte Duschdauer zählt ab dem ersten Anstieg statt ab der Unterbrechung (vorher z. B. „ca. 1 min“ statt etwa 8 min).
- Startmeldung unterscheidet „keine Temperatur eingerichtet“ von „Temperatur noch nicht verfügbar“ (z. B. während die CCU-Integration noch lädt).

## 1.16.0 – 2026-11-06

- **Positionssensor optional:** Ohne eigenen Sensor kommt die Position vom Cover (`current_position`, sonst offen/zu). Das Sicherheitsnetz nutzt dann das Cover. Bestehende Einrichtungen mit Sensor (HmIP-BROLL Kanal 3) verhalten sich wie bisher.
- Covers ohne Positionssteuerung werden mit `open_cover` geöffnet.
- Neuer Sensor „Position der Luke“. Ohne eigenen Positionssensor nutzen Seitenleiste und Dashboard-Vorlage ihn für den Verlauf.
- **Englisch:** Seitenleiste und Dashboard-Vorlage folgen der Sprache in Home Assistant (Deutsch, sonst Englisch). Englische Übersetzung der Einstellungen vollständig, englische README (`README.en.md`). Protokoll, Benachrichtigungen und Sprachausgabe bleiben deutsch.
- Lizenz GPL-3.0, Beta-Hinweis, Datenschutz- und Haftungsabschnitt in der README, Hinweis zur Entstehung mit KI-Unterstützung.
- Vorlagen für Fehlermeldungen und Ideen auf GitHub (mit Bitte um die Diagnose-Datei).
- Einstellungstext zu Bright Sky nennt die Übermittlung der gerundeten Koordinaten.
- Mindestversion in `hacs.json` auf HA 2026.2.0 (älteste getestete Version).
- Gerät zeigt als Hersteller „Community (HACS)“.

## 1.15.0 – 2026-11-04

- **Sturmschutz:** Bei Böen ab einer einstellbaren Schwelle (Standard 60 km/h) schließt die Luke, auch nach Handöffnung und bei ausgeschalteter Automatik. Eine Handöffnung bei Sturm wird wieder geschlossen. Die Automatik öffnet erst 30 min nach der letzten Böe über der Schwelle wieder. Quelle sind die gemessenen Böen der DWD-Station (Bright Sky), sonst Böe oder Wind der Wetter-Entität (Einheit wird umgerechnet). Einstellbar unter *Wetter und Öffnungsweite*.
- Status-Attribute `boeen`, `boeen_quelle`, `sturmsperre`.
- **Reparaturhinweise** unter Einstellungen → System → Reparaturen: Luke schließt nicht, Luke öffnet nicht, Feuchte- oder Positionssensor fehlt, Thermostat übernimmt die Lüft-Temperatur nicht, DWD-Messwerte seit über einer Stunde nicht erreichbar. Sie verschwinden von selbst, sobald die Ursache behoben ist.
- **Diagnose-Download** auf der Integrationsseite (⋮ → Diagnose herunterladen): Einstellungen, aktueller Zustand, Werte aller Quell-Entitäten, gelernte Referenz, Zähler und vollständiges Protokoll. Der Name des Benachrichtigungsdienstes wird geschwärzt.
- **Automatische Prüfungen auf GitHub:** Tests gegen die festgelegte und gegen die neueste HA-Version, hassfest und HACS-Prüfung. Releases werden aus diesem Changelog erzeugt.
- Tests laufen jetzt gegen HA 2026.10.4.

## 1.14.0 – 2026-11-04

- Herkunft von Handbedienungen: Benutzer (Dashboard, App), Automation oder Skript mit Namen. Ohne Aufruf in HA: „außerhalb von HA (Taste am Gerät, CCU-Programm oder Direktverknüpfung)“.

## 1.13.0 – 2026-11-03

- Auskühlschutz: automatische Lüftung endet unter einer Mindest-Raumtemperatur (Standard 18 °C), eigener Zähler.
- Sensor „Feuchte an kältester Wand“ (Verfahren wie HA Mold Indicator, Kalibrierfaktor einstellbar, Start 1,3).
- Optionaler Vorhersage-Sensor für die Lüftdauer wird mit der tatsächlichen Dauer verglichen.

## 1.12.1 – 2026-11-03

- HmIP-Thermostate mit eigener Fenster-auf-Funktion werden erkannt. Übernimmt das Thermostat die Lüft-Temperatur nicht, greift die Integration nicht mehr in die Heizung ein.

## 1.12.0 – 2026-11-03

- Fehlerfälle nachgestellt und abgesichert: wiederhergestellte Tasten-Entität, Schließ- oder Öffnungsbefehl ohne Wirkung, ausgefallener Positionssensor, nicht erreichbares Thermostat.
- Regen-Haltezeit 15 min. Bei ausgeschalteter Automatik bleibt eine Handöffnung offen.

## 1.11.1 – 2026-11-03

- Behoben: Ein Positions-Update ohne Bewegung wurde als „von Hand geschlossen“ gewertet, die Luke stand danach den ganzen Tag offen.
- Neues Sicherheitsnetz alle 2 min (`KORREKTUR`).

## 1.11.0 – 2026-11-02

- Dashboard: Raumfeuchte als großer Wert, Abschnitt Heizung mit Thermostat.

## 1.10.0 – 1.10.1 – 2026-11-02

- DWD-Messwerte der nächsten Station über Bright Sky, optionaler Regensensor.
- Dashboard-Schalter schalten direkt und leuchten im Ein-Zustand.

## 1.7.0 – 1.9.3 – 2026-11-02

- Dashboard-Vorlage mit Bubble Card, Mushroom und mini-graph-card, manuelle Steuerung, Zeitraum-Auswahl, Sensornamen an den Diagrammen.

## 1.4.0 – 1.6.1 – 2026-11-02

- Zweiter Feuchtesensor für die Raumluft, Lüfter läuft mit der Luke, übliche Raumfeuchte als Ziel, nicht während des Duschens schließen, weiche Nachlüftzeit.

## 1.0.0 – 1.3.0 – 2026-11-01

- Erste Version als Integration mit Steuerung, Analyse und Seitenleiste. Danach: Nachlüften ab Duschende, absolute Feuchte, Stagnation, ausführlicheres Protokoll.
