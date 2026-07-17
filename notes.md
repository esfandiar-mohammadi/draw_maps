## 2026-07-17 — SSL→Finetune-Pipeline (BEIDE Zweige) läuft; ~20h durch Orchestrierungsfehler verloren

GOTCHA (teuer, ~20h): Orchestrator-Skript hatte als Stufe 0 eine Warteschleife
`while pgrep -f "train_jepa.py"; do sleep 120`. Meine eigenen Monitoring-Watcher
(until-loops) enthielten „train_jepa.py" in ihrer Kommandozeile → der
Orchestrator-pgrep matchte DIE (Selbstmatch, exakt der CLAUDE.md-pgrep-Gotcha)
→ Stufe 1 wurde nie erreicht, obwohl JEPA um 21:28 fertig war. FIX: Orchestrator
per PID gekillt, neu gestartet OHNE Warteschleife (JEPA-ckpt existiert eh),
direkt Stufe 1. LEHRE: Orchestrator-Warteschleifen NIE auf pgrep von Datei-
namen, die auch in Beobachter-Kommandos vorkommen — auf Artefakt/Logzeile warten.

Beide SSL→Finetune-Ketten (User-Wunsch: SSL dann Finetune, auf DINOv2 UND HEAT):
- DINO-Zweig: I-JEPA-Backbone (dino_vitg_jepa.pt) → train_dino --backbone_init
  → wall_dino_vitg_jepa.pt → graph_eval_dino → vs 0.896.
- HEAT-Zweig: BYOL-SSL resnet50 (train_byol, CNN-Analogon zu JEPA: EMA-Target +
  Predictor, Latent-Loss, keine Negatives) → inject_byol_heat (318/318 tensors,
  module.base_model.* prefix) → HEAT-Finetune 300ep → heat_eval → vs 0.908.
Sequenziell (parallel ViT-g+resnet OOMt). Stufe 1 läuft: JEPA-Backbone sauber
geladen (missing 0), 58% real / 159 reale Kacheln.

## 2026-07-16 — JEPA-Domänenanpassung des DINO-Backbones läuft (User-Daten)

User lieferte 507 GEKAUFTE Drakkenheim-Battlemaps (Nextcloud-Link, 2.3 GB ZIP,
NUR Bilder, KEINE Wand-GT). Lizenz: gekauft → nur lokal, NICHT weitergeben
(corpus/drakkenheim/, in .gitignore). User-Direktive: Teil ausgehalten lassen,
Rest für SELF-SUPERVISED Feature-Learning via JEPA.
- Split `pipeline/jepa_split.py` (ordnerweise, seed 0): 124 Bilder (24%)
  HELD-OUT/unbenutzt, 383 → JEPA-SSL-Pool. Listen in corpus/drakkenheim_split/.
- `pipeline/train_jepa.py`: I-JEPA (Assran 2023, Config in1k_vith14_ep300)
  auf DINOv2-ViT-g. ECHTES Token-Dropping (Context-Encoder sieht Targets nie —
  sonst trivialer Loss), Prediction im LATENTRAUM, EMA-Target-Encoder, Smooth-L1,
  Multi-Block-Maske (1 Context 0.85–1.0, 4 Targets 0.15–0.2, aspect 0.75–1.5,
  patch14, EMA 0.996→1.0, Predictor depth12/emb384). Speicher: nur letzte 6
  Backbone-Blöcke + Predictor trainierbar (192.6M), frozen prefix no_grad,
  Target-Encoder volle EMA-Kopie no_grad bf16. Smoke 3 steps OK (kein OOM).
- Läuft: 6000 steps bs16, Loss 0.68→0.57 @100. Modell → dino_vitg_jepa.pt.
- WARUM: DINOv2 ist auf Fotos vortrainiert; 383 unlabeled gemalte Maps >> 89
  gelabelte → JEPA passt Features an die Zieldomäne an, DANN supervised
  Fine-Tune (DinoSeg mit dino_vitg_jepa.pt statt hub-Init) + Eval vs. 0.896/0.908.

## 2026-07-16 — HEAT fine-tuned = NEUES BESTMODELL: F1 0.908 (DINO 0.896)

Volles HEAT-Fine-Tune fertig (300 Ep., 5:51 h, ab finetune_init_battlemaps_256,
2338 Crops/83 Maps, checkpoint_best in ckpts_heat_battlemaps_full). Eval
`heat_eval_uvtt.py --image_size 256` auf den 6 harten Maps, MIT
drop_border_edges (HEAT halluziniert DENSELBEN Bildrand-Rahmen wie die
Seg-Modelle — Filter aus graph_infer wiederverwendet, festival P 0.31→0.72):

| Map | DINO 0.896er | HEAT-ft |
|---|---|---|
| void-town | 0.81 | **0.89** |
| goblin-travel-train | 0.94 | **0.95** |
| desert-tavern | 0.97 | **0.98** |
| road-side-in | **0.92** | 0.81 |
| festival-of-fools | **0.88** | 0.82 |
| little-fish-academy | 0.85 | **0.99** |

**MEAN HEAT-ft P=0.853 R=0.981 F1=0.908.** Verlauf HEAT: zero-shot 0.296 →
fine-tuned 0.848 → +Randfilter 0.908. HEAT gewinnt 4/6, ausgerechnet die
DINO-Schwächen (little-fish 0.99, void-town 0.89); DINO bleibt vorn auf
road-side + festival. Oracle-per-map wäre 0.935 → **Ensemble ist der nächste
Hebel** (Kanten-Merge + gegenseitige Verifikation über die jeweils andere
Wandwahrscheinlichkeit). Overfitting-Sorge (Val-corner_recall 0.34) hat sich
auf den ausgehaltenen Maps NICHT bestätigt — Val-Split ≠ harte Maps.
PRODUKT-WICHTIG: HEAT ist 49M Params/~190 MB (vs. DINO 1.14B/4.6 GB) und
liefert nativ WENIGE gerade Segmente (51–110/Map, H4-freundlich, editierbar).
Trainings-Gotcha: keine — Lauf sauber. Eval-Detail: heat_eval nutzt 256er-
Kacheln; 512er-Variante ungetestet (Checkpoint ist 256er-Init).

## 2026-07-15 — real_uvtt-Harvest abgeschlossen: 27 validierte reale Maps mit Wand-GT

Fortsetzung des UVTT-Harvests: alle Dateien unter `corpus/real_uvtt` mit
`pipeline/uvtt.py` validiert (Bild dekodierbar + walls>0), SHA256-Dedupe gegen
`vendor/vtt-maps` (62 Dateien, 0 Überschneidung) und untereinander.
**27 gültige Maps**: Akesari12 7, pleonr/HotDQ 9 (13 wandlose Outdoor-Maps →
`_no_walls/`), SangzorDeGeit 5 (+1 aussortiert), oganm 1, Imagix/uvtt2fgu 1
(neu, BSD-3), **BBEG Adventures 4 (neu)**. BBEG: 0-€-Gast-Checkout (EDD-Shop,
Bestellungen #97–#99) → Forgotten Crypt + Tomb of the Forgotten 5E/SD VTT-Packs;
1 byte-identisches Duplikat → `_dupes/`. „The King's Inn" ist SERVERSEITIG
kaputt (Download-Link → 404-Seite statt ZIP; 3× verifiziert, auch direkte
wp-content-URL 404) → ggf. support@bbegadventures.com. Lizenz BBEG (INFO.txt):
Nutzung ok, „do not redistribute … including free assets" → nur lokal.
Provenienz/Lizenzen komplett in `corpus/real_uvtt/README.md`.
Nicht frei zugänglich (User müsste manuell): Cze&Peku-Sample-Pack
(Foundry-Login-Modul, 25 Maps mit Wänden!), Tom Cartos/MikWewa/Aonbarr
(Patreon). gmcrafttavern: nur Bilder ohne Wanddaten. GOTCHA EDD:
Download-Links sind Einmal-Tokens; abgebrochener curl = Limit verbraucht →
neuer 0-€-Checkout nötig.

## 2026-07-15 — Bildrand-Filter: F1 0.834 → 0.896 (+0.06) — NEUER BESTWERT

Root cause der festival-Schwäche: Modell halluziniert Wand-RAHMEN am Bildrand.
Fix systemisch in `graph_infer.build_graph`: `drop_border_edges` (Kante fliegt,
wenn BEIDE Endpunkte <12 px an derselben Bildkante liegen; wirkt für alle
Aufrufer). Re-Eval identisches Protokoll: festival P 0.36→0.82 / F1 0.52→0.88,
little-fish 0.84→0.85, alle anderen Maps UNVERÄNDERT (kein Regress, Effekt
feuert nur am Ziel — H8 ✓). **MEAN DINO-GRAPH P=0.871 R=0.926 F1=0.896.**
Overlay festival geprüft: Rahmen weg, Gebäude/Stände bleiben; eine Geisterlinie
links übrig. Nebenbei: doppelten `import math` in graph_infer bereinigt (F811).

HEAT-Zwischenergebnis (Agent): **Zero-Shot MEAN F1=0.296** (P=0.37 R=0.28) —
Satellit→Battlemap überträgt NICHT (road-side 0.00, desert-tavern 0.12).
Vorsicht Eyeballing: das schöne HEAT_zeroshot_desert-tavern-Overlay zeigt
GT+Prediction — die Zahlen entlarven es (H2!). ABER: dd2vtt→S3D-Konverter
(`pipeline/dd2vtt_to_heat.py`, 2338 Crops in corpus/heat_data) läuft, Smoke-
Train (5 Ep.) lernt gesund (Loss 751→206, corner_recall steigt). Nächster
Schritt: volles Fine-Tune 300 Epochen (~7,5 h) ab finetune_init_battlemaps_256,
dann heat_eval_uvtt.py mit dem neuen Checkpoint gegen DINO 0.896.

## 2026-07-15 — DINO-DURCHBRUCH: ViT-g-Graph F1 0.834 (vorher 0.738) — NEUES BESTMODELL

DINOv2-ViT-g-Fine-Tune fertig (5 Epochen, best val Dice 0.436 — niedriger als
ResNet 0.50, aber val=donjon-Domäne; der TRANSFER ist, was zählt). Eval:
`pipeline/graph_eval_dino.py` (DinoSeg + wall_dino_vitg.pt, 252er-Kacheln,
sonst IDENTISCHES Protokoll wie graph_eval_uvtt; Baseline dazu frisch
reproduziert: MEAN 0.650/0.943/0.738 ✓).

| Map | ResNet F1 | DINO F1 |
|---|---|---|
| void-town | 0.59 | **0.81** |
| goblin-travel-train | 0.85 | **0.94** |
| desert-tavern | 0.91 | **0.97** |
| road-side-in | 0.74 | **0.92** |
| festival-of-fools | 0.41 | **0.52** |
| little-fish-academy | **0.93** | 0.84 |

**MEAN DINO-GRAPH P=0.791 R=0.926 F1=0.834** (+0.096; Precision +0.14 bei fast
gleichem Recall). 5/6 Maps besser. Overlays angesehen (H2): void-town alle 5
Gebäude sauber, wenig Clutter; festival-of-fools zeigt die Restschwäche:
**falscher Wand-Rahmen am BILDRAND** + einzelne Geisterlinien (P=0.36) →
nächster billiger Hebel: Randband-Filter im Graphbau oder Rand-Augmentierung.
little-fish -0.09: einzige Regression, noch nicht analysiert.
**Konsequenz: DINO-ViT-g ist das neue Backbone.** (Inferenzkosten beachten:
1.14B-Modell, 4.6 GB Checkpoint — für das Foundry-Produkt später ggf.
Distillation ins U-Net via Pseudolabels.)

HEAT-Zwischenstand (Agent lief vor dem Limit weiter als gedacht): CUDA-Ops
GEBAUT (Egg im venv), Checkpoints outdoor-256/512 + s3d-256 geladen, Zero-Shot-
Overlays in corpus/results/HEAT_zeroshot_*.png — Qualität: saubere recht-
winklige Polygone mit wenigen Ecken (genau H4-Repräsentation), aber lückige
Abdeckung auf map02. Läuft jetzt: numerische HEAT-Zero-Shot-Eval + dd2vtt→
S3D-Format-Konverter + Smoke-Train (Agent). Zweiter Agent: real_uvtt-Harvest
(36 GitHub-Dateien validieren, BBEG-0€-Checkout fortsetzen, README/Lizenzen).

## 2026-07-15 — UNTERBROCHEN (Org-Spend-Limit), Wiederaufnahme in ~5 h

Zwei Hintergrund-Agenten starben am API-Limit, Arbeit HALB fertig — bei
Wiederaufnahme fortsetzen:
1. **HEAT-Eval** (vendor/heat, evtl. schon teilgeklont): Repo woodfrog/heat,
   Zero-Shot mit Outdoor-Checkpoint auf map02/desert-tavern/road-side-in →
   Overlays nach corpus/results/HEAT_zeroshot_*.png; dann Fine-Tuning-Plan.
   Agent-Zwischenstand: S3D-Dataset-Klasse ist die saubere Vorlage fürs eigene
   Datenformat (keine externen Corner-Files nötig); ein 512er-Inferenz-Lauf war
   evtl. noch offen. Prüfen: existiert vendor/heat? Checkpoints geladen? Ops
   gebaut?
2. **UVTT-Harvest** (corpus/real_uvtt/): BBEG-Adventures-Checkout für 0-€-Items
   funktionierte (Warenkorb-Flow), Agent war beim Einsammeln weiterer Free-Items.
   Prüfen: was liegt schon in corpus/real_uvtt/, README/Provenienz nachziehen,
   jede Datei mit pipeline/uvtt.py validieren (walls>0), SHA256-Dedupe gegen
   vendor/vtt-maps.
3. **DINOv2-Training läuft LOKAL WEITER** (unabhängig vom API-Limit, PID
   3820153): danach DINO-Eval vs. F1 0.74 (siehe Handoff-Eintrag unten).

## 2026-07-15 — Grounding DINO zero-shot GEPRÜFT: zu verrauscht als direkter Fix

Hypothese aus OBJECT_MODELS.md („Grounding DINO findet bridge/chimney/water →
Graph-Korrektur") empirisch getestet: `IDEA-Research/grounding-dino-base`
(transformers 5.13.1, zero-shot), Prompt „a bridge. a chimney. stairs. water.
a boat. a tower. a tree. a wagon. a house roof.", Full-Image + 1024er-Kacheln,
auf map02-Stadt + 5 harten dd2vtt-Maps. Overlays: scratchpad `GDINO_*.jpg`,
Zähl-Summary `gdino_summary.json`.
- **Brauchbar:** Bäume (map02 konsistent), Wasser grob (Kanal/Fluss bekommt
  Boxen, aber fragmentiert), einzelne Treppen.
- **NICHT brauchbar als Fix:** „bridge"/„chimney" hochgradig unzuverlässig —
  ganze Gebäude/Dächer werden „a bridge" (map02, road-side), Token-Merge-Labels
  („a bridge a boat a wagon"), Kachel-Pass erzeugt Box-Spam (void-town praktisch
  nur Rauschen: Särge=boat, Bänke=chimney). Genau die Objekte, die unsere
  Wandfehler verursachen, sind die unzuverlässigsten.
- **Verdikt:** zero-shot Grounding DINO ist ein SCHWACHES Signal, kein
  plug-and-play-Fix. Nutzbar höchstens für Wasser/Baum-Maskierung mit strengen
  per-Klasse-Schwellen + NMS + SAM-Masken-Verifikation. Brücken/Schornstein-
  Korrektur darüber: Hypothese in dieser Form WIDERLEGT.
- User-Redirect daraufhin: (1) **HEAT** (github.com/woodfrog/heat, CVPR 2022,
  Bild→planarer Graph end-to-end, ggf. auf unsere Daten fine-tunen — dd2vtt-GT
  ist exakt das Corner+Edge-Format!) herunterladen & testen; (2) **mehr echte
  UVTT-Daten** (kostenfreie Quellen: BBEG Adventures, Aonbarr, …) harvesten —
  Real-Anteil war der bewiesene Hebel. donjon-Harvest gestoppt bei ~143,5k.

## 2026-07-15 — DINOv2 ViT-g Fine-Tune läuft (Handoff vor /clear)

Warum: testen, ob stärkere vortrainierte Features (DINOv2 ViT-g/14, 1.1B, emb 1536)
den ResNet34-U-Net-Graphen (F1 0.74) auf harten Maps schlagen. DINOv3 war gated
(401) → DINOv2 (User: "option 2"). Raw-DINO-Segmentierung (dino_features.py, PCA/
KMeans) sah gut aus → daher fine-tunen statt nur probing.
- `pipeline/train_dino.py`: `DinoSeg` = torch.hub dinov2_vitg14, **letzte 4 Blocks
  + norm** auftaubar, Decoder-Head (Conv→GN→GELU ×2 →2ch). 2 Kanäle (Wand+Junction),
  gleiche Losses wie Graph (BCE+Dice+0.4·clDice + Junction-BCE + node_reg·mean).
  SZ=252 (18×14). `--donjon_cap 8000` hält Real-Anteil hoch (**55% real**).
- STATUS bei /clear: läuft im Hintergrund (PID 3820153 +8 DataLoader-Worker),
  GPU 96%, noch Epoch 1, **noch kein Checkpoint** `wall_dino_vitg.pt` gespeichert
  (speichert nur bei bester Val-Dice). donjon-Harvest bei 142k/200k.
- **NACH DEM TRAINING PRÜFEN:** Schlägt es F1 0.74? Braucht DINO-spezifische
  Inferenz — `graph_infer.predict` lädt aktuell den smp-U-Net. Also: DinoSeg laden
  → wall/junc vorhersagen → `graph_infer.build_graph` → `graph_eval_uvtt`-Metrik
  auf denselben 6 harten Maps (void-town, goblin-travel-train, desert-tavern,
  road-side-in, festival-of-fools, little-fish-academy). Wenn schlechter: beim
  ResNet-Graphen (wall_graph_unet.pt) bleiben, DINO als Objekt-/Semantik-Backbone
  weiterverwenden statt als Wand-Segmentierer.
- DANACH: Objekterkennung (Grounding DINO, OBJECT_MODELS.md) für Brücken/
  Schornsteine → verschränkter Detektion↔Segmentierungs-Loop → Precision heben
  (aktuell 0.65, Über-Detektion ist die Schwäche).

## 2026-07-15 — Planarer Graph gelernt (Punkte + Kanten + Dicke/Kante)

`pipeline/train_graph.py`: 2-Kanal-U-Net (ch0 Wand-Footprint, ch1 Junction-
Heatmap), letzte 8 Layer, clDice, + **Knoten-Sparsity-Reg** (L1 auf Junctions,
node_reg=0.02) → wenige Knoten. Junction-Labels = geclusterte Skelett-deg≠2-
Punkte. `pipeline/graph_infer.py`: Junction-Peaks=Knoten, Wand-Skelett+DP=Kanten,
**Dicke pro Kante** (Distanztransform), **Knoten-Reduktion** (kollineare Kanten
über Grad-2-Knoten mergen, nahe Knoten snappen).
- Stadt-Map: 827 Knoten, 646 Kanten, Dicke 1.9–24.2 px (Median 5.7). Graph folgt
  Gebäudeumrissen sauber, Knoten an Ecken. `PLANAR_GRAPH_map02.png`.
- Wall-Val-Dice 0.50 (leicht unter Single-Channel-Footprint 0.54 — Kapazität auf
  2 Kanäle geteilt). Knoten noch etwas viel → stärkere Reg/Merge möglich.

# notes.md — session log (newest on top)

## 2026-07-14 — Gelernte Wanddicke (Footprint-Labels)

Labels von Linie → **Wandfläche** (dunkles Material um GT-Centerline, echte Dicke;
`build_real_tiles.build_dd2vtt` Footprint). Modell lernt variable Dicke; parallele
Kanten = eine gefüllte Region → Merge IM NETZ (kein Postprocessing-Heuristik mehr,
adressiert User-Einwand). Vektorisierer: skelettiert Footprint → Mittellinie,
Dicke = 2·Distanztransform. Real-Anteil auf 32% hochskaliert (real_mul=65, da
donjon-Harvest gewachsen).
- Ergebnis harte Maps (fair, Centerline-Vergleich): **P=0.57 R=0.83 F1=0.66**.
  Stadt-Map Dicke variiert 1.9–16.4 px (Median 5.7). `LEARNED_thickness_map02.png`.
- TRADEOFF: leicht schlechter als Thin-Line-Modell (F1 0.73), weil Skelett einer
  dicken Region weniger präzise lokalisiert + Footprint-Labels verrauschter.
- **Sauberste Lösung (Vorschlag):** 2-Kanal-Modell = dünne Centerline-Segmentierung
  (präzise) + separate Dicke-Regression. Beides ohne Skelett-Wander.

Bug behoben: `pkill -f train_seg.py` erlegte eigenen Wrapper (Exit 144). donjon-
Harvest bei ~28k, läuft weiter.

## 2026-07-14 — DURCHBRUCH: Domänen-Mix + clDice auf harten Maps

Modell: last-8, donjon 10.5k + 26% reale gemalte Kacheln (dd2vtt-GT + Reddit-
Pseudolabels), grid-invariant, BCE+Dice+0.4·clDice.
**Harte ausgehaltene Maps (dd2vtt GT): MEAN P=0.657 R=0.874 F1=0.727.**
(little-fish 0.95, desert-tavern 0.94, void-town 0.83, road-side 0.79). Verlauf:
CV 0.22 · SAM 0.39 · last-4-donjon F1 0.48 · last-8-donjon F1 0.43 → **jetzt 0.73**,
Precision fast verdoppelt bei hohem Recall. Hebel = reale Daten im Training +
Verbundenheits-Loss (NICHT mehr donjon). Heatmap sauber, Vektorisierer Stadt-Map
239 Gruppen (statt 2561), lange verbundene Züge. `FINAL_map02_mix_cldice.png`.

OFFEN (User): Wanddicke soll GELERNT werden (variiert). Plan: Labels =
Wandfläche (gefülltes Material echter Dicke) statt fester Linie; dd2vtt-Footprint
aus GT-Centerline + dunklem Material ableiten; Modell segmentiert Fläche →
Skelett = Mittellinie, Dicke = Distanztransform; parallele verschmelzen ohne
festen thickness-Parameter.

## 2026-07-14 — Regularisierung: clDice (Verbundenheit) + Dicke (Parallel-Merge)

User-Wünsche eingebaut:
1. **Lange, verbundene Linien / Trennung braucht Evidenz:** `soft_cldice` in
   `train_seg.py` (centerline-Dice, differenzierbar, iterative Soft-Skeleton).
   Loss = BCE + Dice + 0.4·clDice. Bricht das Modell eine Linie, sinkt die
   Topologie-Precision/Sensitivity → höherer Loss → lange verbundene Wände.
2. **Parallele wenige px auseinander = zwei Seiten einer Wand → via Dicke:**
   `vectorize_walls.vectorize(thickness=6)` — MORPH_CLOSE mit Wanddicke-Kernel
   verschmilzt parallele Kanten zu einem Band, dessen Skelett EINE Mittellinie
   ist. Schließt auch kleine Lücken (längere Linien).
Training läuft neu: donjon 10.5k + real 138×25 (26% real), last-8, grid-invariant,
+ clDice. donjon-Harvest bei ~10.5k, läuft weiter.

## 2026-07-14 — last-8 Ergebnis: WICHTIGER Overfitting-Befund

last-8 (23.1M Params) vs last-4 (0.2M), beide grid-invariant, 200k aug:
- donjon val Dice: 0.34 (last-4) → **0.57 (last-8)** — tieferes Fine-Tuning fittet
  die Trainingsdomäne (donjon) klar besser.
- ABER harte REAL-Maps (dd2vtt GT): last-4 P=0.37/R=0.80/F1=0.48 →
  **last-8 P=0.37/R=0.585/F1=0.43** — Recall FÄLLT (0.80→0.59)!
- **Interpretation:** last-8 passt den Encoder an donjons Pixel-Art-Look an →
  überfittet die synthetische Domäne, überträgt SCHLECHTER auf gemalte Maps. Der
  eingefrorene Encoder (last-4) hielt generische ImageNet-Features → besserer
  Transfer. Kontraintuitiv aber sauber gemessen.
- **Konsequenz:** MEHR donjon-Daten (200k-Harvest läuft, bei ~6.8k) verbessert
  nur den donjon-Fit, NICHT den Transfer (Domänenkluft, kein Datenmangel). Echter
  Hebel: reale dd2vtt-Maps + High-Confidence-Pseudolabels INS TRAINING mischen
  (Domänenanpassung), evtl. last-4/geringere Encoder-Anpassung + starke
  Stil-Augmentierung.
- Vektorisierer auf Stadt-Map: min_len-Pruning 2561→513 Gruppen; Polylinien
  folgen Wänden, aber fragmentiert (Maske durch Domänenkluft nicht kohärent
  genug für saubere Gebäude-Loops). `vectorize_citymap_groups.png`.

## 2026-07-14 — Piecewise-lineare verbundene Polylinien + last-8 + Fixes

- **Polylinien-Repräsentation (`pipeline/vectorize_walls.py`):** Wand-Maske →
  threshold → skeletonize (skimage) → Skelett-Graph (Knoten/Kreuzungen) →
  Polylinien nachzeichnen → Douglas-Peucker → Gruppen = Zusammenhangskomponenten.
  Ergibt stückweise lineare, in kleinen Gruppen verbundene Kurven (nicht
  rasterbeschränkt) — die vom User gewünschte Repräsentation. Test auf sauberer
  donjon-Maske: 26 klare Gruppen. Auf Stadt-Map (mit v1-Maske): folgt
  Gebäudeumrissen, aber fragmentiert (2561 Gruppen) wegen verrauschter v1-Maske →
  braucht saubere v2-Maske + stärkeres Fragment-Pruning.
- **Strukturierter Grid-Kanten-Output** (edge_data.py) verworfen zugunsten der
  flexibleren Polylinien (User: Raster-only zu streng). edge_data-Labels waren
  auf dekorativen Dungeons unzuverlässig (Zellerkennung täuscht sich).
- **last-8 statt last-4** (`set_finetune_last8`): head + 5 Decoder-Blöcke +
  encoder.layer4 + layer3. Training neu gestartet (GPU 94%).
- **Bug behoben:** verkettete Hintergrund-Befehle mit Newlines kollabierten →
  Training lief nie an; jetzt über run_in_background sauber.

Offen: v2/last-8 fertig trainieren → Maske sauberer → vectorize_walls mit
Fragment-Pruning auf Stadt-Map → saubere Polylinien-Gruppen; harte-Map-Zahlen.

## 2026-07-14 — Skalierung + Fixes (User-Direktiven)

- **200k-Datensatz:** 200 000 *distinct* donjon-Renders = ~400k Requests an einen
  Gratis-Server = missbräuchlich → NICHT gemacht. Stattdessen: diverse Basis
  (`pipeline/donjon_harvest2.py`, parallel, gedrosselt, Ziel ~2500 Dungeons,
  `grid=None`) + **200 000 augmentierte Samples** (Standard-ML-Praxis, respektiert
  donjon). Basis in `corpus/donjon/base`.
- **Letzte 4 Layer (Korrektur):** vorher layer3+4 des Encoders; jetzt in
  `train_seg.py` `set_finetune_last4` = segmentation_head + letzte 3
  Decoder-Blöcke (ausgangsseitig), Encoder eingefroren.
- **Grid-Invarianz:** `add_random_grid` überlagert beim Training zufällige Raster
  (Größe/Farbe/Offset/Alpha) bzw. lässt sie weg → Modell lernt Raster ≠ Wand
  (behebt den Wald-/Textur-Fehlerfall). Plus Crop/Flip/Rot/Color-Jitter.
- **Verbundene Wandlinien (Postprocessing):** `pipeline/seg_to_walls.py` — Seg-
  Wahrscheinlichkeit → aufs Raster snappen → kollineare zu langen Läufen mergen,
  Rauschlücken überbrücken aber Tür-große Lücken offen lassen → Endpunkt-Schweißen
  (Verbindung für Licht) → isolierte Stummel entfernen. Nutzt grid_walls-Maschinerie.

Training läuft (letzte 4 Layer, grid-invariant, 200k aug. Samples). Danach:
Eval auf harten Maps + Postprocessing-Vergleich.

## 2026-07-14 — donjon GEKNACKT + Segmentierungsmodell (erstes echtes ML-Ergebnis)

**donjon-Datengenerierung gelöst** (`pipeline/donjon_harvest.py`): gleicher
seed+params rendert identische Geometrie in jedem map_style. Standard-Stil
(weißer Boden/schwarzer Fels) → Bodenmaske schwellwerten → Wandmaske (Rand der
Bodenfläche; Türen = Lücken bleiben offen). Hübscher Stil (Parchment/Slate/…) =
Trainingsbild. Pixelgenau ausgerichtet, unbegrenzt. 220 Paare generiert
(preview.cgi cappt ~199×259). Belege: `corpus/results/donjon_label_extraction.png`,
`donjon_training_pairs.png`.

**Segmentierungsmodell** (`pipeline/train_seg.py`): smp U-Net, ResNet34-Encoder
(ImageNet). Fine-Tune TIEFE Layer (encoder.layer3+layer4 + Decoder + Head; ~23M
Params), nicht nur Head (User-Direktive). RandomForest verworfen. Val-Dice ~0.34
(dünne Linien → Dice pessimistisch).

**Harte-Map-Eval gegen dd2vtt-GT** (`pipeline/seg_eval_uvtt.py`):
MEAN P=0.374 **R=0.803** F1=0.480 (desert-tavern F1=0.74!). Vorher CV/SAM:
P~0.22–0.39 bei R~0.44. **Durchbruch = Recall 0.44→0.80** — Modell findet jetzt
die meisten Wände. Precision (0.37) noch schwach: überfeuert auf Raster/Textur
(Wald-Map: donjon ist rasterlastig → Modell lernt Gitter=Wand). Transfer auf
gemalte Stadt-Map trotz Domänenkluft gut (`SEG_map02_town_donjon_trained.png`).

**Nächste Hebel (Precision):** Grid-Removal-Augmentierung (nicht Gitter=Wand
lernen), echte dd2vtt + High-Confidence-Pseudolabels ins Training mischen
(Domänenanpassung), mehr/größere donjon-Daten, Grid-Snapping als Post-Processing.

## 2026-07-14 — Confidence-Charakterisierung + ehrlicher Reality-Check

**Confidence via Detektor-Übereinstimmung** (`pipeline/confidence_eval.py`, gegen
dd2vtt-GT, inkl. harter Maps): Precision CV=0.218, SAM=0.387, **AGREE=0.516**
(R_agree=0.562). Auf harten Maps aber niedrig: void-town P_agree=0.19,
goblin-travel-train=0.25. → Zwei-Detektor-Übereinstimmung verdoppelt Precision,
reicht aber NICHT für saubere Pseudolabels auf harten Bildern. Ein echtes
Confidence-Modell (mehr Signale: Kontrast, Lauflänge, Loop-Zugehörigkeit,
Grid-Konf) nötig, um bei hoher Schwelle P~0.9 (low recall) zu erreichen.

**donjon:** Bild per `preview.cgi?seed=...&params...` unbegrenzt abrufbar, aber
die WAND-DATEN liegen client-obfusziert (kein Global/Endpoint gefunden;
download_json(json) bekommt json als Arg). Unbegrenzte GELABELTE donjon-Daten =
entweder Export knacken oder robuster ein prozeduraler Generator (Bild+Maske).

**Ehrlicher Gesamtstand:** Detektion (CV & SAM) auf harten Maps real bei
P~0.2–0.4 — wie vom User gesagt inakzeptabel. Der Weg zu echtem Fortschritt
(Confidence-Modell → Pseudolabels + synthetische/donjon-Daten → Segmentierungs-
modell fine-tunen → Eval auf harten Maps) ist ein mehrstufiges Projekt, kein
Quick-Win. Kein Vortäuschen von Fortschritt.

## 2026-07-14 — Pretrained-Embeddings statt Handmerkmale (User-Kritik)

Fairer Vergleich (dd2vtt-Labels, ausgehalten, `pipeline/emb_region_clf.py`,
DINOv2 ViT-S/14 frozen):
- Handmerkmale (RF):        Requisite P=0.891 R=0.959 | keepR=0.452 | acc=0.870
- DINOv2-Embedding (LogReg): Requisite P=0.892 R=0.921 | keepR=0.479 | acc=0.843
- **Embedding + Handmerkmale: Requisite P=0.906 | keepR=0.548 | acc=0.862** (bestes P + keepR)
Erkenntnis: Embedding ALLEIN schlägt Handmerkmale NICHT — weil Crop→224 die
absolute Größe zerstört (dominantes Signal für Raum/Requisite). Kombiniert am
besten. Kombimodell: `pipeline/models/region_clf_emb.joblib`.

**Tiefergehend (beide User-Fragen zeigen dieselbe bessere Architektur):** Der
Region-Filter auf SAM ist ein Aufsatz mit begrenztem Deckel. Der eigentliche
Gebrauch vortrainierter Features = ein **Segmentierungsmodell end-to-end
fine-tunen** (sieht volle Auflösung, verliert keine Größe) auf reichlich Labels.
Label-Quellen bereit: dd2vtt (62) + **donjon** (unbegrenzt; Bild+JSON mit
Wänden, vom Universal-Donjon-Importer bestätigt; Export-UI dynamisch → braucht
Browser-Harvester). donjon-Export nicht im statischen DOM sichtbar.

## 2026-07-14 — Schritt 2 FERTIG: echt-gelabelter Region-Klassifikator + echte Eval

Kenney verworfen (nur Spritesheet ohne Kategorien + Pixel-Art-Domänenkluft;
In-Domain-Weak-Labeling entartet: 7 keep vs 318 prop). Lösung über die zweite
User-Bitte („andere gelabelte Battlemaps finden"): **mbround18/vtt-maps** (62
echte .dd2vtt = Bild + Wände + Türen) geklont nach `vendor/vtt-maps`. Parser
`pipeline/uvtt.py` (base64-PNG + line_of_sight-Polylinien in Grid-Einheiten →
Pixel-Segmente). GT-Overlay verifiziert: perfekte Gebäude-Umrisse + Türen.

- **Real-gelabelter Klassifikator** (`pipeline/train_region_clf.py`,
  `models/region_clf.joblib`): SAM-Region = keep, wenn Grenze auf GT-Wänden
  liegt, sonst prop. RandomForest auf 8 Form-/Farbmerkmalen. Test (ausgehalten):
  prop P=0.92/R=0.98 (Requisiten zuverlässig erkannt), keep P=0.79/R=0.51.
  Wichtigste Merkmale gelernt: area_frac, sat, solidity.
- **Integriert** in `sam_walls.py` (`use_classifier`, `drop_thr=0.8`: nur sicher
  erkannte Requisiten verwerfen).
- **Echte Eval gegen GT** (`pipeline/eval_uvtt.py`, ausgehaltene Maps):
  Klassifikator hebt Precision OHNE Recall-Verlust (road-side-in 0.45→0.50;
  Mittel P 0.338→0.361). Absolut noch grob (P~0.36/R~0.44) — ehrlich gemessen.
  Generalisiert auf Reddit-map02: 260→210 Wände, 219 Requisiten verworfen.
- Grid-Detektion scheitert auf einigen dd2vtt (großes ppg, schwaches Sichtraster)
  → Fallback ohne Grid gibt (noch) keine Wände aus. Offener Punkt.

Weitere gefundene Label-Quellen: donjon-Generator (Bild+Wand-JSON, unbegrenzt),
Dungeon-Alchemist-JSON. Nächster Schritt (User-Plan): 3 = live in Foundry v13.

## 2026-07-14 — Schritt 1 (größeres Modell) fertig; Schritt 2 Datenquelle geklärt

**Schritt 1 (Recall via größeres Modell):** FastSAM-x vs FastSAM-s vs SAM2.1-b
verglichen. FastSAM-x segmentiert am dichtesten (298 Regionen), SAM2.1-b nur 46
(untersegmentiert, Standard-Punktraster zu grob). FastSAM-x jetzt Default in
`pipeline/sam_walls.py` (Bug gefixt: model_name wurde nicht durchgereicht).
map02: 225→260 Wände, +18% Länge, sichtbar vollständigere Umrisse. Bild:
`corpus/results/COMPARE_map02_FastSAMs_vs_FastSAMx.png`. Modelle: FastSAM-s/x.pt,
sam2.1_b.pt im Projektroot.

**Schritt 2 (FA-Klassifikator) — Datenquelle BLOCKIERT:** FA-Einzelassets sind
Patreon-geschützt (Browser kommt auf die Seite, aber Assets hinter „Login with
Patreon"; Live-Gallery zeigt nur Produkt-Thumbnails). Von hier nicht frei
abgreifbar. Alternativen: (a) User stellt FA-Patreon-Zugang / lädt freies FA-Pack;
(b) In-Domain-Weak-Labels aus dem Korpus (kleine kompakte SAM-Regionen = Prop/
Nicht-Wand; Rauminneres = Boden; Grid-Linien-Patches = Wand) → domänen-passend,
kein Download nötig. Empfehlung: (b) jetzt bauen, FA später ergänzbar. Auf
User-Entscheidung wartend.

## 2026-07-14 — Wechsel zu ML: Recherche + SAM-Prototyp begonnen

User: klassisches CV reicht nicht → ML. Zwei Richtungen (beide recherchiert &
verifiziert, Quellen in `ML_TRAINING_DATA.md`):
- **Trainingsdaten:** UVTT/.dd2vtt = fertige (Bild+Wände)-Paare (Kernquelle;
  github.com/mbround18/vtt-maps, freie Foundry-Packs Czepeku/FA); CubiCasa5K
  (5000 Grundrisse, Wände-Polygone, Zenodo) zum Pretraining; synthetische
  Generierung für Skalierung.
- **Negativbeispiele (User-Idee):** Asset-Packs (Forgotten Adventures) sind nach
  Kategorien geordnet → Ordner = Labels. Nicht-Wand-Kategorien (Floors, Nature,
  Furniture, Props) = fertige Negativbeispiele gegen Requisiten-FPs. Gratis in
  der Live-Gallery. → Wand/Nicht-Wand-Klassifikator.
- **SAM (User-Idee):** SAM segmentiert Regionen, nicht Linien → Wände =
  Grenzen zwischen begehbaren Regionen. Prototyp `pipeline/sam_walls.py` speist
  SAM-Regionsgrenzen als Wandmaske in die bestehende Grid-Nachverarbeitung
  (Snap/Merge/Weld/Prune). Nutzt Ultralytics FastSAM.

**ML-Umgebung EINGERICHTET & SAM-PROTOTYP LÄUFT:** torch 2.13.0+cu130 (CUDA
aktiv auf Blackwell), ultralytics 8.4.95, `.venv`. `pipeline/sam_walls.py` mit
FastSAM-s: auf map02 in ~1,3 s 229 Regionen → 85 nach Flächenfilter →
Regionsgrenzen als Wandmaske → Grid-Snap/Merge/Weld/Prune → 225 rastergerechte
Wände. Ergebnis SAUBERER als CV v3: folgt Gebäudeumrissen, dunkle Teppich-FPs
weg, weniger Requisiten-FPs — OHNE Handabstimmung der Erkennung. Recall stellen-
weise etwas niedriger. Bilder: `corpus/results/COMPARE_map02_CV_vs_SAM.png`,
`map02_SAM_regions.png`. FastSAM-s.pt liegt im Projektroot (22 MB).
Nächste Hebel: größeres Modell (FastSAM-x/SAM2) für Recall; FA-Klassifikator als
Wand/Nicht-Wand-Filter der Regionen; Türerkennung.

## 2026-07-14 — Grid-Erkennung verbessert (Kontrast, Dedup, Verbinden, Prune)

User-Anforderung: (a) Erkennung verbessern, (b) sehr ähnliche/parallele Segmente
zusammenfassen + verbinden (sonst Lichteffekte kaputt), (c) Parallele wenige px
apart = zwei Seiten EINER Wand. Umgesetzt in `pipeline/grid_walls.py` v2/v3:

- **Kontrast-Scoring statt absoluter Dunkelheit:** Wand = dunkler *Grat* als die
  hellere der beiden Nachbarzellen (`score = Grat - min(Nachbar-Zell-Dunkelheit)`).
  Killt Falschpositive im Inneren dunkler Flächen (Teppiche, dunkle Fliesen) —
  vorher das Hauptproblem (crop_center war ein volles FP-Gitter, jetzt leer).
- **Kontinuitäts-Gate (coverage):** dunkler Grat muss Kante überspannen → Dekor/
  Requisiten (patchy) fallen raus. + Grün/Laub heruntergewichtet (HSV).
- **Parallel-Dedup:** zwei parallele Wände 1 Feld apart mit Wandmaterial
  dazwischen (dunkle Zelle) = eine Wand → eine behalten (map02: 111, map03: 929
  entfernt). Korridor (Boden dazwischen) bleibt zwei Wände.
- **Lücken schließen + Endpunkt-Schweißen:** kollineare Läufe mit kleinen Lücken
  überbrückt; lose Enden bis 1 Feld verlängert, um kreuzende Wände zu treffen
  (alles auf Integer-Grid → gemeinsame Knoten → Lichteffekte funktionieren).
- **Isolierte Stummel beschneiden:** kurze Wände, die nichts verbinden, sind
  meist Falschpositive (Requisiten) → entfernt (Verbindung als FP-Filter).

**Messung map02 (Stadt):** Baseline-Kanten 4305 Wände/39% achsengerecht →
Grid v1 (nur Dunkelheit) 626/100% → Grid v3 (verbessert) 422/100%, 71 Doppel
entfernt, Teppich-FPs weg. Vergleichsbilder:
`corpus/results/COMPARE_map02_v1_darkness_vs_v3_improved.png`,
`map02_town_GRID_v3.png`, `map02_crop_{center,building}_v3.png`.

Dispatcher `pipeline/auto.py` fixiert (neue Signatur `k=`). Offen: helle
Requisiten (Teppich/Karren) teils noch umrandet (Objekterkennung nötig);
Türerkennung (offene Gaps als door statt Wand); Farb-Clustering für Wandfarben.

## 2026-07-14 — Grid-basierter Spezialfall (User-Hypothese) gebaut & verifiziert

**Hypothese (User):** Maps haben meist ein Raster, Wände laufen entlang, Raster
ist meist eine runde Pixelzahl. **Verifiziert** (nicht nur geglaubt):
- Rastererkennung (`pipeline/grid_detect.py`, Sobel-Projektion + Comb-Filter,
  Grundfrequenz-Reduktion + quadratisches Raster erzwungen): map01/02/03/07 alle
  **grid=70 px** (runde Zahl!), Konfidenz 3.6–7.7; grünes Overlay lag exakt auf
  dem karteneigenen Raster. Hafen map08: Konf 2.4 → kein verlässliches Raster
  (viel Wasser), fällt korrekt aus dem Spezialfall.

**Spezialfall (`pipeline/grid_walls.py`):** testet jede Rasterkante auf
Wand-haftigkeit (Band-Mittel der Dunkelheit = Dicke×Dunkelheit; dünne
Rasterlinie niedrig, dicke Wand hoch), adaptiver Schwellwert (Median+k·MAD),
snappt Wände exakt aufs Raster, fasst kollineare Kanten zu langen Segmenten.

**Messung Baseline (Kanten) vs. Grid-Spezialfall:**
| Map | Modus | Wände | %achsengerecht | Median-Länge |
|---|---|---|---|---|
| map02 Stadt | Baseline | 4305 | 39% | 8px |
| map02 Stadt | GRID (k=1.2) | 626 | **100%** | 40px |
| map03 Jahrmarkt | Baseline | 4371 | 17% | 7px |
| map03 Jahrmarkt | GRID | 1366 | **100%** | 24px |
→ ~7× weniger Wände, 0% falsche Diagonalen (statt 61%/83%), ~5× längere Segmente.

**Dispatcher (`pipeline/auto.py`):** Grid-Konfidenz ≥3.0 → Grid-Modus, sonst
generischer Kanten-/Kontur-Detektor (Fallback für rasterlose Maps wie map08).
Verifiziert: map02→GRID, map08→generic.

Ergebnisbilder: `corpus/results/COMPARE_map02_baseline_vs_grid.png`,
`map0{2,3}_*_GRID.png`. Offene Verbesserungen: Überdetektion in textur-/dekor-
dichten Zonen (Grid-Modus setzt dort teils Wände auf Bodenmuster); mehrere
Wandfarben clustern; Türen erkennen.


## 2026-07-14 — Wanderkennung auf echten Reddit-Battlemaps getestet

**Aufbau:** Reddit-API/HTML blockiert diese IP (403), aber `i.redd.it` (Bild-CDN)
ist erreichbar. 8 Battlemaps via Browser (`scratchpad/reddit_scrape.py`) aus
r/battlemaps, r/dndmaps, r/dungeondraft geholt → `corpus/maps/`. Erkennung mit
der **Auto-Wall-Engine** (geklont nach `vendor/auto-wall`, headless über
`pipeline/detect.py`; deps in `.venv`: opencv-python-headless, numpy, sklearn,
scipy, Pillow). Kern: `detect_walls()` + `contours_to_foundry_walls()` (liefert
direkt Foundry-Wandformat `c:[x0,y0,x1,y1]`). Overlays in `corpus/results/`.

**Wichtige Klarstellung:** Das Modul `auto-wall-companion` erkennt KEINE Wände —
es importiert sie nur. Erkennung = Auto-Wall (CV). Getestet wurde also die
Erkennungsqualität + der Import-Pfad.

**Ergebnis (voll-automatisch, ohne manuelles Tuning):**
- Architektonische Maps (Stadt map02, Hafen map08): viele echte Wände gefunden,
  ABER Kantenmodus erzeugt lange **falsche Diagonalen** über offene Flächen und
  ist überfragmentiert (>4000 Segmente; verletzt H4). Precision niedrig.
- Farbmodus (auto-gesampelte dunkle Wandfarbe) auf map02: falsche Diagonalen
  weg (hohe Precision), aber erfasst nur Wände genau dieser Farbe → niedrige
  Recall (obere Gebäude verpasst).
- Organische Maps (Wald map01, Schlucht map07): schlecht — Kantenerkennung
  verhakt sich in Laub/Textur, fast nur Rauschen.
- map04 (Illustration), map05/map06 (Regionalkarten): keine Battlemaps mit
  Wänden — ungeeignet by design.

**Fazit:** Voll-automatisch ist nur ein grober Startpunkt (Trade-off Recall vs.
Precision). Auto-Wall ist bewusst SEMI-automatisch (Nutzer wählt Wandfarben +
editiert Maske). Das deckt sich mit den CLAUDE.md-Hypothesen (H4, Precision auf
farbigen Maps). Der Import-Pfad ins Modul ist separat schon in v13 verifiziert.
NOCH NICHT gemacht: eine echte Erkennung + Map-Hintergrund in Foundry importieren
(angeboten als nächster Schritt).

## 2026-07-14 — LIVE-Test auf Forge erfolgreich (Foundry v13.351)

**Ergebnis:** Das wiederbelebte Modul läuft nachweislich in echtem Foundry v13.
Verifiziert auf der Forge-Instanz `eisenwind.forge-vtt.com` (Browser-Automation
via Playwright, headless Chromium, `.venv`):
- Modul via Manifest installiert (gehostet in der Forge-Asset-Library des
  Users: `https://assets.forge-vtt.com/66bd035aa699217f6678098e/module.json`
  + `.../auto-wall-companion-2.0.0.zip`). Foundry meldete "installed successfully".
- Modul aktiv (`game.modules.get("auto-wall-companion").active === true`),
  API geladen (`window.AutoWallCompanion` === object) → init/ready-Hooks laufen
  fehlerfrei.
- Scene-Control-Buttons integriert MIT `onChange` (v13-Migration): alle 3
  (wall-management, copy-scene-image, export-tiles) in `ui.controls...walls.tools`.
- DialogV2 (v13-Migration) öffnet + rendert korrekt ("Wall Management").
- End-to-End: `importWallsFromClipboard()` erstellte 5 Wände in der Szene
  (before=0 → after=5), auf dem Canvas sichtbar.
- Beweis-Screenshots: `test-evidence-v13-{toolbar,dialogv2,walls-imported}.png`.

**Zustand der Instanz nach dem Test (OFFENE Aufräum-Entscheidung):**
- Foundry-Version wurde v11.315 → **v13.351** hochgestellt (Forge-Konsole:
  Version-Select → "Änderungen speichern" → Server-Neustart). NICHT der
  "Aktualisierung auf v13"-Link (der tat nichts) — der Select+Speichern war nötig.
- Bestehende Welt `dndbeyond-itsi` (v11/dnd5e): UNBERÜHRT, nie in v13 geöffnet →
  nicht migriert. Vor dem v13-Wechsel via "Return to Setup" deaktiviert, sodass
  "Derzeit gestartete Welt = Keine" → beim v13-Boot wird sie nicht geladen.
- Neu angelegt: Welt `wall-test` (System daggerheart, v13-nativ) + System
  `daggerheart` (versehentlich statt worldbuilding installiert). Aktuell aktiv.
- **Wichtige Erkenntnis:** Das Modul braucht v12+. Auf der ursprünglichen v11
  ist es NICHT nutzbar. Nutzung erfordert, dass die Instanz auf v12+ bleibt —
  was für die Hauptwelt dndbeyond-itsi eine (irreversible) v13-Migration bedeuten
  würde.

**User-Entscheidung (2026-07-14):** Instanz bleibt auf **v13** (nicht zurück auf
v11). **Nichts aufgeräumt** — wall-test, daggerheart und das Asset-Hosting
bleiben bestehen. Browser-Automations-Session beendet; wall-test-Welt bleibt
serverseitig aktiv. OFFENER Hinweis an User: dndbeyond-itsi erst nach
Backup/Modul-Kompatibilitätscheck in v13 öffnen (Migration ist irreversibel).

**Browser-Automations-Harness:** `scratchpad/forge/driver.py` (persistenter
Playwright-Treiber, Kommando-Queue via `cmds/`), `send_cmd.sh`. Login-Captcha
(niedrigster Würfel) manuell gelöst. Node: `~/.nvm/versions/node/v24.18.0/bin`.


## 2026-07-14 — Auto Wall Companion revived (v2.0.0, unreleased)

**What:** User asked to revive the archived module
https://github.com/ThreeHats/auto-wall-companion (archived 2025-07-15 in favor
of Universal Battlemap Importer). Revival is justified: the module fills a
niche the importer does not — importing walls into an EXISTING scene +
copying the scene image URL for Auto-Wall; the importer only creates NEW
scenes from UVTT.

**Where:** clone at `vendor/auto-wall-companion`, branch `revival`, commit
5e9920a. Installable zip: `vendor/auto-wall-companion/auto-wall-companion-2.0.0.zip`.

**Changes:** onClick→onChange for v13+ scene-control tools (verified:
https://foundryvtt.com/api/v13/interfaces/foundry.SceneControlTool.html);
Dialog(V1, deprecated since v13)→DialogV2 for both dialogs;
foundry.utils.saveDataToFile; deprecation chat spam removed; build no longer
writes to hardcoded Windows AppData path (FOUNDRY_DATA_PATH opt-in);
version 2.0.0, compatibility min 12 / verified 14; README rewritten.

**Verification:** `npm run build` clean (tsc + vite); `node test/smoke.mjs`
PASSED — headless test with stubbed Foundry globals covering: settings
registration, global API exposure, v13-record and v12-array control shapes,
onChange presence, padding warning via DialogV2, 250-wall import batching
(100/100/50), wall export round-trip, scene-image-URL resolution.
NOT yet verified: live behavior in a real Foundry v13/v14 world (needs the
Forge instance or a local install — next step).

**Environment set up this session:** Node via nvm at
`~/.nvm/versions/node/v24.18.0/bin` (export PATH before npm/node).

**Open:** (1) live test on the user's Forge instance (login
theforge@esfandiar-mohammadi.de; password in chat only, never store);
(2) publishing: GitHub fork under user's account for manifest-URL installs —
ask first; (3) dist/style.css builds empty and is dead template code — could
be removed entirely.
