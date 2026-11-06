# Änderungen

Neue Versionen erscheinen in HACS als Update, sobald ein Release mit Tag `vX.Y.Z` existiert. Es entsteht über den Workflow `Release` (Actions → Release → Run workflow, Versionsnummer eingeben). Er legt Tag und Release nur an, wenn alle Prüfungen grün sind.

## 1.15.1 – 2026-11-06

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
