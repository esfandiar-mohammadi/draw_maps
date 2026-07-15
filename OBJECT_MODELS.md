# Objekterkennung auf Top-Down-Battlemaps — Modelloptionen (2026-07-15)

Problem: Wand-Detektion verwechselt Objekte — Brücken werden als Fassaden-
Verlängerung gelesen, Schornsteine als neues Gebäude/Gebäudeende. Ziel: ein
Objekt-Verständnis, das solche Elemente erkennt und die Wandgraph-Korrektur
speist. Recherchiert & per URL geprüft.

## A) Offene Objekterkennung (direktester Fix für benannte Objekte)  ← Empfehlung
Zero-Shot, per Text-Prompt — man nennt genau die Problemobjekte.
- **Grounding DINO + SAM = Grounded-SAM / Grounded-SAM-2** (IDEA-Research):
  Text-Prompt → Detektion → SAM-Maske. Prompts wie "wooden bridge", "chimney",
  "rooftop", "tower", "stairs", "water", "tree". https://github.com/IDEA-Research/Grounded-Segment-Anything
- **YOLO-World** (Ultralytics): schnelle Open-Vocabulary-Detektion per Prompt.
- Vorteil: kein Training; auf riesigen, diversen Web-Bildern (inkl. Illustrationen)
  vortrainiert → überträgt vermutlich BESSER auf stilisierte Maps als satelliten-
  spezifische Modelle. Nutzung: Brücke → begehbar (keine Wand); Schornstein →
  Teil des Gebäudes (kein neues Gebäude/Ende); Wasser/Bäume → maskieren.

## B) Luft-/Satelliten-Foundation-Modelle (Overhead-Domäne, Gebäude-Extraktion)
Blickwinkel (von oben) passt; Stil (echte Fotos vs. gemalt) NICHT → Domänenkluft,
am besten als Backbone zum Fine-Tunen auf unseren Daten.
- **SatlasPretrain** (Ai2): Foundation-Modelle für Satelliten- UND Luftbilder,
  Gebäude-Segmentierung, Gewichte verfügbar. https://allenai.org/blog/satlaspretrain-models-foundation-models-for-satellite-and-aerial-imagery-1679ebe4bbfb
- **Prithvi-EO-2.0** (IBM/NASA) via **TerraTorch** (unterstützt Prithvi, Granite,
  Clay, SatMAE, Satlas, DOFA). **Clay v1.5** (offenes EO-FM).
- **Gebäude-Footprint-Modelle** auf INRIA / SpaceNet / Massachusetts Buildings;
  pip `building-footprint-segmentation`. INRIA: https://project.inria.fr/aerialimagelabeling/
- Übersicht: https://github.com/Jack-bo1220/Awesome-Remote-Sensing-Foundation-Models
- CAVEAT: trainiert auf ECHTEN Satellitenfotos → Transfer auf gemalte Maps
  unsicher ohne Fine-Tuning.

## C) Panoptische Segmentierung (semantische Klassen)
- **Mask2Former / OneFormer** auf ADE20K (Klassen u.a. building, house, bridge,
  tower, wall, fence). ABER: Boden-Perspektive → Domänenkluft zu Top-Down.

## Empfohlener Weg
1. **Sofort & zielgenau:** Grounded-SAM/Grounding DINO per Prompt die
   Problemobjekte (bridge, chimney, tower, water, stairs) segmentieren → als
   Zusatzkanäle/Regeln in die Graph-Korrektur (Brücke=begehbar, Schornstein→
   Gebäude verschmelzen). Kein Training, adressiert exakt die genannten Bugs.
2. **Mittelfristig:** semantischen Layer (Gebäude/Boden/Wasser/Brücke) lernen —
   entweder aus (1) als Pseudolabels oder Fine-Tuning eines SatlasPretrain-
   Backbones auf donjon+dd2vtt+Pseudolabels.
