[README.md](https://github.com/user-attachments/files/33754796/README.md)
# G-Lab ClothForge

### FiveM Clothing Toolkit

Ein Python-Tool zum Erstellen, Verwalten, Prüfen und Optimieren von
FiveM-Kleidungs-Resources. Es verarbeitet Addon-Kleidung und
Ersatz-Mods, erstellt die benötigten Resource-Dateien und bietet eine
browserbasierte 3D-Vorschau.

## Funktionen

-   **Automatische Erkennung:** `.ydd`, `.ytd` und `.yld` -- auch wenn
    Dateien uneinheitlich benannt oder sortiert sind.
-   **Addon- und Ersatz-Mods:** automatische Zuordnung; Ersatzdateien
    bleiben unverändert.
-   **Automatische Resource-Erstellung:** `.ymt`, `.meta` und
    `fxmanifest.lua`.
-   **Nummernverwaltung:** fortlaufende Nummern je Geschlecht und
    Kategorie; mehrere Packs können zusammengeführt werden.
-   **An bestehende Resource anhängen:** bestehende Nummern bleiben
    erhalten, Duplikate werden erkannt.
-   **Große Packs:** ab mehr als 256 Teilen pro Kategorie werden weitere
    DLCs angelegt.
-   **Aufteilen nach Kategorie:** getrennte Resources, z. B. für
    Oberteile, Hosen, Haare und Ersatzdateien.
-   **Texturoptimierung:** große Texturen prüfen und auf eine gewählte
    Maximalgröße reduzieren.
-   **Dateiprüfung:** beschädigte Kleidungsdateien erkennen und bei
    Bedarf durch Platzhalter ersetzen.
-   **3D-Vorschau:** Kleidung und Texturvarianten am Charakter ansehen
    und durchblättern.
-   **Sicheres Löschen:** gelöschte Teile werden archiviert; Platzhalter
    schützen bestehende IDs.
-   **Mapping-Datei:** `clothing_mapping.csv` dokumentiert die Zuordnung
    der Original- zu den neuen Dateinamen.

## Voraussetzungen

-   Python **3.10 oder neuer**
-   Windows empfohlen
-   Keine zusätzlichen Python-Pakete erforderlich

Bei der Python-Installation unter Windows die Option **„Add python.exe
to PATH"** aktivieren.

## Schnellstart

1.  `start.bat` starten.
2.  Den Ordner mit den Kleidungsdateien auswählen. Unterordner werden
    durchsucht; `.zip`- und `.oiv`-Dateien werden automatisch entpackt.
3.  Einen Ausgabeordner auswählen, z. B. `resources/[kleidung]`.
4.  Einen Resource-Namen vergeben, z. B. `glab_clothes`.
5.  Optional einen Probelauf ausführen, um die erkannten Dateien zuerst
    zu prüfen.
6.  **Resource bauen** auswählen.
7.  Die Resource in der `server.cfg` starten:

``` cfg
ensure glab_clothes
```

Für weitere Kleidung kann dieselbe Resource über **„An bestehende
Resource anhängen"** ergänzt werden.

## Addon oder Ersatz-Mod?

Das Tool unterscheidet die Dateitypen automatisch:

-   **Addon-Kleidung:** wird als neues Kleidungsstück mit eigener Nummer
    eingebunden.
-   **Ersatz-Mod:** ersetzt ein vorhandenes GTA-Kleidungsstück; die
    ursprüngliche Nummer bleibt erhalten.
-   **Hauttexturen und Ersatzdateien:** werden unverändert in
    `stream/replacements/` übernommen.

Die Zuordnung wird im Log angezeigt. `.rar`- und `.7z`-Archive müssen
vorher mit 7-Zip entpackt werden; `.rpf`-Dateien mit OpenIV.

## Ressourcen aufteilen

Mit **„Nach Kategorie aufteilen"** erstellt das Tool separate Resources,
etwa für Oberteile, Hosen, Haare und Ersatzdateien. Das kann das
Verwalten und Neustarten einzelner Kategorien erleichtern.

Die Reihenfolge der Resources in der `server.cfg` ist wichtig. Die
erzeugte Datei `ensure.cfg` und das Log zeigen die vorgesehenen
`ensure`-Zeilen. Beim Umwandeln einer bestehenden Resource sollte die
Option zum Anhängen aktiviert werden, damit vorhandene Nummern erhalten
bleiben.

## Texturen optimieren und Dateien prüfen

Im Tab **„Optimieren"** lassen sich bestehende Resources prüfen:

-   Dateien mit hohem Speicherbedarf erkennen.
-   Textur-Maximalgrößen einstellen (z. B. 512, 1024, 2048 oder 4096
    Pixel).
-   Texturen verkleinern.
-   Beschädigte `.ydd`, `.ytd` und `.yld` erkennen.
-   Defekte Dateien bei Bedarf durch Platzhalter ersetzen.

Beim direkten Optimieren werden Originale vor der Änderung in einem
`_original`-Ordner gesichert. Vor größeren Änderungen empfiehlt sich
trotzdem ein zusätzliches Backup der Resource.

## 3D-Vorschau

Im Tab **„3D-Vorschau"** lassen sich Kleidungsstücke und Texturvarianten
am Charakter ansehen.

-   Linke Maustaste: drehen
-   Mausrad: zoomen bzw. durch die Auswahl blättern
-   Rechte Maustaste: Ansicht verschieben
-   Pfeiltasten: Teile oder Texturen wechseln
-   `Bild↑` / `Bild↓`: Slot wechseln

Für eine vollständige Körpervorschau muss der passende Grundkörper aus
einer eigenen GTA-Installation über OpenIV exportiert und im Tool
ausgewählt werden. Das Tool liefert keine Rockstar-Spieldateien mit.

**Hinweis:** Die Vorschau für Props wie Hüte und Brillen am Kopf wird
derzeit noch nicht unterstützt.

## Löschen und Wiederherstellen

Beim Löschen von Addon-Teilen werden Platzhalter eingesetzt, wenn nötig,
damit sich bestehende Kleidungs-IDs nicht verschieben. Gelöschte Dateien
werden in einem `_geloescht`-Ordner archiviert. Mit **Rückgängig**
(`Strg+Z`) können Änderungen zurückgenommen werden. Anschließend die
betroffene Resource im Spiel neu starten.

## Kommandozeile

Resource bauen:

``` bash
python cloth_tool.py "C:\\Downloads\\pack1" "C:\\Downloads\\pack2" -o "C:\\server\\resources\\[kleidung]" -n glab_clothes
```

An bestehende Resource anhängen:

``` bash
python cloth_tool.py "C:\\Downloads\\pack3" -o "C:\\server\\resources\\[kleidung]" -n glab_clothes --append
```

Probelauf ohne Dateien zu schreiben:

``` bash
python cloth_tool.py "C:\\Downloads\\pack1" -o "C:\\server\\resources\\[kleidung]" -n glab_clothes --dry-run
```

Vorschau einer bestehenden Resource:

``` bash
python cloth_tool.py preview glab_clothes
```

Weitere Optionen sind in der Kommandozeilenhilfe des Tools dokumentiert.

## Einschränkungen

-   First-Person-Varianten (`_u_1.ydd`) werden derzeit nicht
    unterstützt.
-   Komprimierte Texturen ohne Mipmaps können derzeit unverändert
    bleiben und werden im Log gemeldet.
-   Für Props am Kopf fehlt aktuell das benötigte Skelett in der
    3D-Vorschau.
-   Addon-Kleidung erscheint im Spiel hinter den Original-GTA-Teilen.
    Die konkrete Drawable-ID hängt von der Ladereihenfolge der
    Kleidungs-Resources ab.

## Tests

``` bash
python -m unittest discover -s tests
```

## Projektdateien

-   `start.bat` -- startet die grafische Oberfläche.
-   `cloth_tool.py` -- Hauptprogramm.
-   `clothing_mapping.csv` -- Zuordnung der verarbeiteten
    Kleidungsdateien in der erzeugten Resource.

------------------------------------------------------------------------

**G-Lab ClothForge** -- FiveM-Kleidung einfacher erstellen, verwalten
und optimieren.
