# Trainingsdaten für ML-Wanderkennung — Rechercheergebnis (2026-07-14)

Ziel: ein Segmentierungsmodell Bild → Wandmaske (danach vektorisieren + aufs
Raster snappen mit dem bestehenden `pipeline/`-Code). Recherchiert & per URL
verifiziert; jede Quelle unten wurde geöffnet/geprüft.

## 1. In-Domain-Labels: UVTT / .dd2vtt = fertige (Bild, Wände)-Paare  ← Kernquelle

Eine UVTT-Datei ist ein Bild **plus** `line_of_sight` (Wände), `portals`
(Türen/Fenster) und Lichter in Rasterkoordinaten — also ein fertiges
Label. „Daten sammeln" = UVTT-/Foundry-Packs mit Wänden sammeln.
- Format: https://arkenforge.com/universal-vtt-files/ ,
  https://dungeondraft-encyclopaedia.gitbook.io/guide/final-steps/exporting-your-map/universal-vtt
- **Direkt klonbar:** https://github.com/mbround18/vtt-maps — Dungeondraft-Quellen
  + exportierte `.dd2vtt` (Bild+Wände) im Repo. Sofort nutzbar.
- Kostenlose Foundry-Packs mit vorkonfigurierten Wänden (Szenen-JSON + Bild =
  Labelpaare): Czepeku Sample Pack (25 Maps)
  https://foundryvtt.com/packages/czepeku-sample-pack , FA Battlemaps
  https://foundryvtt.com/packages/fa-battlemaps .
- UVTT-Parser als Vorlage: https://github.com/Imagix/uvtt2fgu ,
  https://github.com/moo-man/FVTT-DD-Import (zeigen, wie man Wände ausliest).
- Weitere UVTT-Quellen (teils Patreon/Kauf): BBEG Adventures, Tych Maps.
- **Lizenz-Vorsicht:** Maps sind urheberrechtlich geschützt; für privates
  Modelltraining i.d.R. ok, Weiterverbreitung von Daten/Modell nicht ohne Rechte.

## 2. Verwandte Domäne zum Vortrainieren: Grundrisse (Floor Plans)

Architektur-Grundrisse sind wand-annotiert und groß — ideal zum Pretraining,
dann Fine-Tuning auf UVTT/Synthetik.
- **CubiCasa5K:** 5000 Grundrisse, Wände/Türen/Fenster als Polygone (SVG),
  train/val/test-Splits. Code: https://github.com/CubiCasa/CubiCasa5k ,
  Daten (Zenodo): https://zenodo.org/record/2613548 (~105 GB LMDB).
  Lizenz: primär Forschung/nicht-kommerziell — prüfen.
- Weitere: CVC-FP, R-FP, Versailles-FP (arxiv.org/pdf/2103.08064).
- Wiederverwendbarer Modellcode: https://github.com/bjekic/WallSegmentation
  (PyTorch, ADE20K), https://github.com/Divak-ar/floorData (DeepLabV3+).

## 3. Synthetische Daten = unbegrenzt & perfekt gelabelt  ← bester ROI

Selbst generieren, dann sind die Wände per Konstruktion bekannt:
- Battlemaps aus Boden-/Wand-Kacheln komponieren mit exakt bekannter Wandmaske
  (volle Kontrolle über Labels, Zielstil treffbar).
- Watabou One Page Dungeon: Export PNG + JSON/SVG mit Geometrie → Bild + Maske
  ableitbar (kein natives UVTT). https://watabou.github.io/dungeon.html
- Dungeondraft batch-scripten → Map + UVTT-Export (Wände bekannt).
Domain-Gap zu handgemalten Maps via Augmentierung/Stiltransfer verringern.

## 4. Rohbilder (unlabeled) zum Bootstrappen / Testen

Kein fertiges Label, aber nützlich (auto-labeln mit aktuellem CV + Handkorrektur,
oder self-supervised Pretraining, Testvielfalt):
- HF: Zapper/battlemap-1024 (Generator), D&D battlemaps (Civitai),
  neemspees/dnd-battlemaps (ohne Model-Card).
- Reddit r/battlemaps, r/dndmaps (bereits in `corpus/maps/`).

## 5. Negativbeispiele aus Asset-/Tile-Packs — „was ist KEINE Wand"

Asset-Packs sind nach Kategorien geordnet → die Ordner **sind** Labels. Die
Nicht-Wand-Kategorien liefern fertige Negativbeispiele gegen genau unsere
Falschpositive (Teppiche, Karren, Fässer, Pflanzen).
- **Forgotten Adventures** Assets: Kategorien Walls / Floors / Furniture /
  Nature (Pflanzen, Felsen, Bäume) / Terrain-Texturen / Props / Weapons …, als
  einzelne PNG/Webp. Gratis-Auswahl in der Live-Gallery
  (https://www.forgotten-adventures.net/live-gallery/), voll + Dungeondraft-Packs
  Patreon (https://www.forgotten-adventures.net/mapmaking-assets/).
- Nutzung: Klassifikator **Wand vs. Nicht-Wand** trainieren (Walls = positiv;
  Floors/Nature/Furniture/Props = negativ). Ergänzt SAM ideal: jede SAM-Region
  bzw. jeder Kandidat wird als Wand/Nicht-Wand klassifiziert → Requisiten-FPs
  fallen raus. Auch als Bausteine für synthetische Maps (Abschnitt 3).
- Lizenz beachten (privat/Training i.d.R. ok, Weiterverbreitung nicht).

## Empfohlener Weg (Daten → Modell)

1. **Sofort-Labels:** `mbround18/vtt-maps` klonen + freie Foundry-Packs (Czepeku
   Sample, FA) → Wände aus UVTT/Szenen-JSON parsen → kleiner In-Domain-Satz.
2. **Skalieren:** synthetische Battlemaps mit bekannter Wandmaske generieren.
3. **Pretraining:** CubiCasa5K (Wandsegmentierung), dann Fine-Tuning auf 1+2.
4. **Modell:** U-Net/DeepLabV3+ → Wand-Wahrscheinlichkeitsmaske → vektorisieren +
   **das bestehende Grid-Snapping/Merging/Connectivity aus `pipeline/` als
   Post-Processing** (bleibt wertvoll!).
5. **Active Learning:** Reddit-Korpus automatisch labeln, schlechteste
   handkorrigieren, zurückspeisen.
