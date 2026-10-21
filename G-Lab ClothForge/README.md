# G_Lab_ClothTool

Python-Tool für FiveM-Addon-Kleidung. Du gibst ihm Ordner mit Kleidungsdateien (`.ydd`, `.ytd`, `.yld`),
egal wie sie benannt oder sortiert sind, und bekommst eine fertige Resource zurück:

- Dateien werden erkannt (Typ, Nummer, Texturen, Geschlecht) und ins richtige Addon-Format umbenannt
  (`mp_m_freemode_01_<dlc>^jbib_000_u.ydd`, `..._diff_000_a_uni.ytd`, Props mit `_p_`)
- fortlaufende Nummern pro Geschlecht/Kategorie, mehrere Packs werden ohne Kollisionen zusammengeführt
- **`.ymt` wird direkt erzeugt** (binär, kein CodeWalker nötig), dazu `.meta` und `fxmanifest.lua`
- mehr als 256 Teile pro Kategorie → automatisch zweites DLC (`<dlc>_2`) in derselben Resource
- Anhängen an eine bestehende Resource: alte Nummern bleiben gleich, Duplikate werden erkannt
- **Ersatzdateien** (z.B. EUP-Hauttexturen `mp_fm_skin_*.ytd`) werden erkannt und **unverändert** nach
  `stream/replacements/` übernommen – die ersetzen Original-GTA-Dateien und dürfen nicht umbenannt werden
- **Ersetzen-Modus** für Mods, die Original-GTA-Kleidung ersetzen (z.B. Body-Mods): Nummern bleiben,
  die Dateien bekommen den Prefix `mp_f_freemode_01^` / `mp_m_freemode_01^`, damit FiveM die Originale ersetzt
- `clothing_mapping.csv` zeigt, welche Originaldatei welche neue Nummer bekommen hat

## Voraussetzungen
Python **3.10+** (Windows: bei der Installation „Add python.exe to PATH“ anhaken). Keine weiteren Pakete nötig.

## Bedienung (Oberfläche)
`start.bat` doppelklicken (oder `python cloth_tool.py`):

1. **Ordner hinzufügen**: einfach den Ordner, in dem alle Downloads liegen. Er wird komplett durchsucht,
   `.zip` und `.oiv` werden automatisch entpackt. Das Tool entscheidet pro Datei selbst (siehe unten).
   **Als Ersatz erzwingen** nur nutzen, wenn eine Ersatz-Mod nicht erkannt wird
2. **Ausgabe-Ordner** wählen, z.B. `resources/[kleidung]`
3. **Resource-Name** eingeben, z.B. `glab_clothes` (DLC-Name ist standardmäßig derselbe)
4. Optional: **Geschlecht** setzen, wenn es nicht erkennbar ist (siehe unten)
5. **Resource bauen** → in der `server.cfg`: `ensure glab_clothes`

„Nicht erkannte Dateien unverändert übernehmen“ streamt alles, was nicht erkannt wird, mit Originalnamen mit
(z.B. weitere Ersatzdateien aus EUP). Ohne den Haken werden solche Dateien nur im Log gemeldet.

„Probelauf“ zeigt erst mal an, was gefunden wurde, ohne etwas zu schreiben.
Neue Kleidung später dazu: gleicher Ausgabe-Ordner und Name, Haken bei **„An bestehende Resource anhängen“**.

## Bedienung (Kommandozeile)
```
python cloth_tool.py <ordner> [<ordner> ...] -o <ausgabe> -n <resource> [-d dlc] [-r ersatz-ordner] [-g m|f] [--append] [--keep-unknown] [--optimize [px]] [--split] [--dry-run]
python cloth_tool.py preview <resource> [--base <grundkörper-ordner>]

python cloth_tool.py "C:\Downloads\pack1" "C:\Downloads\pack2" -o "C:\server\resources\[kleidung]" -n glab_clothes
python cloth_tool.py -r "C:\Downloads\body_mod" -g f -o "C:\server\resources" -n body_mod
python cloth_tool.py "C:\Downloads\pack3" -o "C:\server\resources\[kleidung]" -n glab_clothes --append
```

## Addon oder Ersatz? (automatisch)
| Datei liegt/heißt … | wird zu |
|---|---|
| `mp_f_freemode_01^uppr_015_r.ydd` oder im Ordner `mp_f_freemode_01` / `mp_m_freemode_01_p` (OpenIV-Export) | **Ersatz** – ersetzt das Original-Teil, Nummer bleibt |
| `mp_f_freemode_01_mp_f_<rockstar-dlc>^…` ohne passende `.ymt` im Pack | **Ersatz** eines DLC-Teils |
| `mp_fm_skin_*.ytd` (Haut-Texturen) | **Ersatz**, unverändert |
| alles andere (`male`/`female`-Ordner, eigene DLC-Namen, Packs mit eigener `.ymt`) | **Addon** – neues Teil, neue Nummer |

Ersatzdateien landen in `stream/replacements/`, Addons in `stream/male|female/…` mit eigener YMT.
Im Log steht für jede Datei, wie sie eingeordnet wurde. `.rar`/`.7z` bitte vorher mit 7-Zip entpacken, `.rpf` mit OpenIV.

## Resource nach Kategorie aufteilen
Häkchen **„Nach Kategorie aufteilen“** (Kommandozeile `--split`): statt einer riesigen Resource entsteht pro Kategorie
eine eigene – z.B. `glab_clothes_jbib` (Oberteile), `glab_clothes_lowr` (Hosen), `glab_clothes_hair` (Haare),
`glab_clothes_ersatz` (Ersatzdateien) – alle im Ordner `[glab_clothes]`. Keine einzelne Resource hängt mehr ewig beim
Serverstart, und man kann z.B. nur die Hosen neu starten.

- **Die IDs im Spiel bleiben gleich**: GTA zählt pro Kategorie, und alle Oberteile bleiben zusammen in derselben
  Reihenfolge. Wichtig: die neuen Resourcen an der Stelle der alten in die `server.cfg` (die Zeilen stehen in
  `[name]/ensure.cfg` und im Log).
- **Bestehende Resource umwandeln:** Häkchen „Aufteilen“ + „An bestehende Resource anhängen“, gleicher Name. Die alte
  Resource wird danach nach `_original/` verschoben, damit nichts doppelt lädt.
- 3D-Vorschau, Optimieren und „Defekte ersetzen“ funktionieren auch mit dem ganzen `[name]`-Ordner.

## Texturen verkleinern (Tab „Optimieren“)
Meldungen wie `Asset … uses 32.0 MiB of physical memory` bedeuten: die Datei braucht zu viel Grafikspeicher –
fast immer wegen riesiger Texturen (oft eingebettete 4096er Normal-/Spiegelungs-Maps in der `.ydd`). FiveM warnt ab
16 MiB pro Datei; große Dateien machen außerdem den Serverstart und das Joinen langsam.

- **Beim Bauen:** Häkchen **„Texturen verkleinern“** (Standard an, max. 1024 px).
- **Bestehende Resource:** Tab **„Optimieren“** → Ordner wählen → **Prüfen** zeigt jede Datei mit Speicher
  (rot = über 16 MiB), größter Textur und dem Wert nach dem Verkleinern. **Jetzt verkleinern** ändert die Dateien
  direkt; die Originale kommen vorher nach `_original/<ordner>/<zeit>/` neben dem Ordner.
- Maximale Größe einstellbar für Textur, Normal-Map und Spiegelung (512/1024/2048/4096). Standard 1024 – wie bei
  grzyClothTool und den meisten FiveM-Kleidungspacks; aus normaler Spielentfernung sieht man keinen Unterschied.
- So funktioniert es: GTA-Texturen enthalten ihre kleineren Stufen schon (Mipmaps). Das Tool lässt die größten Stufen
  weg – nichts wird neu komprimiert, die neue Textur ist pixelgenau die nächstkleinere Stufe. Das Modell bleibt unverändert.
  Unkomprimierte Texturen ohne Mipmaps (A8R8G8B8 u. ä., oft riesige Normal-Maps) werden direkt herunterrechnet.
  Komprimierte Texturen ohne Mipmaps (z.B. 4300×4300 DXT1) bleiben bisher unverändert und werden im Log gemeldet.
- Kommandozeile: `python cloth_tool.py optimize <ordner> [--max 1024] [--apply]`, beim Bauen `--optimize [px]`.

**Defekte Dateien** (z.B. FiveM-Absturz „Invalid fixup, address is neither virtual nor physical“): Das Tool prüft jede
`.ydd`/`.ytd`/`.yld` so, wie FiveM sie lädt – alle internen Zeiger müssen gültig sein, die Datei vollständig.
- Beim **Bauen** kommen defekte Dateien gar nicht erst in die Resource (Warnung im Log). Sind sie schon in der
  Resource (Anhängen), werden sie durch Platzhalter ersetzt, damit sich keine IDs verschieben.
- Im Tab **„Optimieren“** stehen defekte Dateien rot ganz oben, mit Grund. **„Defekte durch Platzhalter ersetzen“**
  repariert eine fertige Resource auf diese Weise.

## 3D-Vorschau
Tab **„3D-Vorschau“**: zeigt die Teile aus der fertigen Resource am Charakter, im Browser (drehen: linke Maustaste,
zoomen: Mausrad, verschieben: rechte Maustaste). Pro Slot (Oberteil, Hose, Schuhe …) wählst du Teil und Textur
(a, b, c …), darunter die Liste aller Addon- und Ersatz-Teile zum schnellen Durchklicken. Die Auswahl merkt sich der Browser.

Schnell durchblättern: **Mausrad** über der Teil- bzw. Textur-Auswahl, die **◀ ▶**-Knöpfe, oder per Tastatur im
aktiven Slot (Zeile anklicken): **↑/↓** Teil, **←/→** Textur, **Bild↑/Bild↓** nächster Slot.

Für den Charakter braucht das Tool einmalig den **Grundkörper** aus deinem Spiel (Rockstar-Dateien liefert das Tool
nicht mit): in OpenIV `x64v.rpf › models › cdimages › streamedpeds_mp.rpf › mp_f_freemode_01.rpf` öffnen und den
Inhalt in einen Ordner `mp_f_freemode_01` exportieren (Männer: `mp_m_freemode_01`). Diesen Ordner als
„Grundkörper-Ordner“ wählen. Ersatz-Teile aus der Resource ersetzen dabei die Original-Teile – so siehst du z.B.
Body-Mods direkt am Körper. Ohne Grundkörper wird nur die Kleidung angezeigt.

**Löschen:** „Teil löschen“ / „Textur löschen“ unter den Slots, das 🗑 in der Liste oder die Taste **Entf**
(**Umschalt+Entf** = Textur). Damit sich keine IDs verschieben (gespeicherte Outfits bleiben heil), kommt an die Stelle
eines gelöschten Addon-Teils ein unsichtbarer **Platzhalter** – nur das jeweils letzte Teil bzw. die letzte Textur wird
ganz entfernt. Gelöschte Ersatz-Teile werden einfach entfernt (im Spiel ist dann wieder das Original zu sehen).
Die Dateien landen in `_geloescht/<resource>/<zeit>/` neben der Resource, **Rückgängig** (Strg+Z) holt sie zurück.
YMT und Meta werden sofort neu geschrieben – danach im Spiel `restart <resource>`.
Beim nächsten **Anhängen** füllen neue Teile zuerst die Platzhalter auf (gleiche Nummer), der Rest kommt hinten dran.

Noch nicht dabei: Props (Hüte, Brillen …) am Kopf – dafür fehlt noch das Skelett.

## Was erkannt wird
| Datei | Beispiel |
|---|---|
| Drawable | `jbib_000_u.ydd`, `uppr_003_r.ydd`, `mp_f_freemode_01_irgendwas^lowr_012_u.ydd` |
| Textur | `jbib_diff_000_a_uni.ytd`, `uppr_diff_003_a_whi.ytd` |
| Cloth-Physik | `jbib_000_u.yld` |
| Props | `p_head_000.ydd`, `p_head_diff_000_a.ytd` (auch `p_eyes`, `p_ears`, `p_lwrist`, …) |

Kategorien: `head, berd (Masken), hair, uppr (Arme), lowr (Hosen), hand (Taschen), feet (Schuhe),
teef (Accessoires), accs (Unterhemden), task (Westen), decl (Decals), jbib (Oberteile)`.

**Geschlecht** kommt aus dem Prefix (`mp_m_freemode_01…` / `mp_f_freemode_01…`) oder aus einem Ordnernamen
(`male`, `men`, `herren`, `m` / `female`, `women`, `damen`, `f`). Sonst das Standard-Geschlecht setzen.

Gut zu wissen:
- Texturen dürfen in einem Unterordner neben dem Drawable liegen; Lücken bei den Buchstaben
  (a, c, d) werden zu a, b, c geschlossen
- Dateien, die nicht erkannt werden, werden übersprungen und im Log gemeldet (nichts geht verloren,
  die Originale werden nur kopiert)
- First-Person-Varianten (`_u_1.ydd`) werden noch nicht unterstützt
- Ein vorhandener Zielordner wird nur ersetzt, wenn er von diesem Tool stammt

## Ausgabe
```
glab_clothes/
  fxmanifest.lua
  mp_m_freemode_01_glab_clothes.meta
  mp_f_freemode_01_glab_clothes.meta
  clothing_mapping.csv
  stream/
    mp_m_freemode_01_glab_clothes.ymt
    mp_f_freemode_01_glab_clothes.ymt
    male/jbib/mp_m_freemode_01_glab_clothes^jbib_000_u.ydd
    male/jbib/mp_m_freemode_01_glab_clothes^jbib_diff_000_a_uni.ytd
    ...
```
Im Spiel liegen Addon-Teile **hinter** den Original-GTA-Teilen. Welche Drawable-ID ein Teil im Kleidungsmenü
genau hat, hängt von der Ladereihenfolge deiner Kleidungs-Resourcen ab. Die Reihenfolge innerhalb dieser Resource
steht in `clothing_mapping.csv`.

## Tests
```
python -m unittest discover -s tests
```
`tests/data/codewalker_reference.ymt` wurde mit CodeWalker.Core erzeugt (gleicher Weg wie im grzyClothTool).
Der Test prüft, dass das Tool Byte für Byte dieselbe YMT erzeugt.
