## 2026-07-22 (04:30) — Wild-Showcase Teil 2: DINO-MS auf denselben 12 unlabeled Maps

`pipeline/dino_infer_showcase.py` (MS-Protokoll wie Benchmark: scales 768/1024/1536,
build_graph, KEIN border-drop = eval-treu). Modell `wall_dino_fa_inscope.pt` (0.728).
Kollagen: `corpus/results/dino_wild_showcase/collage_{reddit,drakkenheim}_dino_ms.png`
(gleiches Layout wie HEAT-Kollagen → direkt vergleichbar).

Visueller Befund (H2) — bestaetigt das Benchmark-P/R-Profil im Wild-Einsatz:
- **DINO = high Precision, low Recall**: KEINE Grid-Halluzination (Black Ivory Inn
  sauber ums Gebaeude, ignoriert schwarzes Raster komplett; Brackish Pool 8 segs
  statt HEATs Grid-Netz), Out-of-scope wird sauber VERWEIGERT (map01 Wald: 9 segs,
  map07 Felscanyon: 12 segs). ABER: map02 Wuestenstadt stark undersegmentiert
  (76 segs vs HEAT ~alle Gebaeude) — der Recall-Mangel ist deutlich sichtbar.
- **HEAT = mehr Recall + Junk**: findet map02/map07 weitgehend, halluziniert aber
  Grids/Terrain.
- Drakkenheim: DINO durchweg sauberer (Kleinburg Outline+Raeume ohne Phantom-Punkte,
  Rose Theatre deutlich besser als HEAT, King's Gate beide exzellent).
Fazit fuer Plan: Wild-Eindruck stuetzt die Strategie „Recall in der Maske pushen"
(DINO laesst echte Waende aus) + Edge-Verification wuerde HEATs Grid-Junk killen.

## 2026-07-22 (04:00) — Wild-Map-Showcase HEAT-ep80 (unlabeled, nie supervised gesehen)

User-Wunsch: 2 Kollagen mit HEAT-Wand-Annotationen auf Maps ohne Label, nicht im
Training. Neues Tool `pipeline/heat_infer_showcase.py` (Inferenz ohne GT, long-edge
1024, drop_border_edges, ROT=pred). Modell: `checkpoint_ep80.pth` (bester in-scope-
HEAT 0.703). Maps: 6 Reddit (`corpus/maps`) + 6 Drakkenheim — beide Pools waren
label-frei im BYOL-SSL-Pool (Backbone-Init), aber NIE im supervised Training.
Kollagen: `corpus/results/heat_wild_showcase/collage_{reddit,drakkenheim}_heat_ep80.png`.

Visueller Befund (H2): STARK auf Top-Down-Gebaeuden (map02 Wuestenstadt, map03
Jahrmarkt-Gebaeude, King's Gate F2 exzellent, Reed Manor gut, Kleinburg-Raeume gut).
SCHWACH/erwartbar: (a) GRID-LINIEN-HALLUZINATION auf leerem/dunklem Hintergrund
(Black Ivory Inn schwarzer Rand, Brackish Pool, map08 Wasser) — HEAT liest das
gezeichnete Raster als Wand; drop_border_edges greift nur am Bildrand, nicht innen.
(b) Out-of-scope-Typen wie erwartet kaputt: Outdoor-Wald (map01, Terrain-Kanten),
isometrische Illustration (map04, fast nichts — korrekt zurueckhaltend), Stadt-
Uebersicht zu weit rausgezoomt (map05). Groesster genereller Fehlermodus im Wild-
Einsatz = Grid-Halluzination → passt zu Plan-Hebel drop_border/Edge-Verification.

Frage User: Distractor-Consistency-Training (Tiles einfuegen, Prediction darf sich
nicht aendern) schon gemacht? NEIN — nur BYOL/JEPA (Representation-SSL) und
supervised Copy-Paste (0.541, verworfen). Als Addendum in DINO_IMPROVEMENT_PLAN.md
aufgenommen (Phase 2 aux loss / Teil von UniMatch-Konsistenz 3.2).

## 2026-07-22 (03:15) — HEAT-in-scope-Arc ABGESCHLOSSEN: Plateau bei 0.703, Training gestoppt

**Ergebnis: HEAT-in-scope-FT schlägt DINO NICHT.** Snapshot-Kurve (in-scope-32,
graph-F1, via Overnight-Monitor): ep50 0.682 / ep60 0.702 / ep70 0.696 / **ep80
0.703** (buildings ~0.69 flach, caves 0.694→0.741→0.738 ausgeflacht). Loss +
edge_acc (0.68) + corner_recall (0.29) ebenfalls flach über viele Epochen →
echtes Plateau über 30 Epochen, alle drei Kurven. Training bei ep84 gestoppt
(User-Regel „bei Graph-F1-Plateau stoppen"; Wrapper + python per PID gekillt,
SIGKILL nötig). GPU wieder frei für Gemma.

**Einordnung:** DINO-MS in-scope bleibt Champion **0.728** (HEAT best 0.703,
Δ −0.025). Die dd2vtt-Buildings-Stärke (0.926) hat NICHT auf FA-in-scope
übertragen (buildings 0.689 < DINO-buildings 0.721!). Caves überraschend HEATs
bessere Hälfte (0.738 ≈ DINO-caves 0.747). **Oracle(DINO,HEAT-ep80) = 0.763**
(+0.035) — Routing-Gate lohnt bei der Decke nicht (Plan-Schwelle ~0.85); HEATs
große Einzel-Wins (sewer-town +0.25, cave-gallery +0.21, mine-caverns +0.13)
besser über Graph-Level-Edge-Merging (Plan 1.4/2.4) einsammeln.
Nachtrag 03:21: Monitor-Schlussmessung `checkpoint_best.pth` (HEATs interner
Val-Pick) = **0.694** < ep80 0.703 → **ep80 ist der beste HEAT-in-scope-Ckpt**;
Monitor hat sich sauber beendet, keine Hintergrund-Jobs mehr offen.
**Nächster Schritt: DINO_IMPROVEMENT_PLAN.md — wartet auf User-Freigabe.**

## 2026-07-21 (spät II) — DINO-Verbesserungsplan geschrieben (NICHT ausgeführt) + ep50-Eval-Crash gefixt

**User-Auftrag: Online-Research + Plan für DINO-Pipeline-Verbesserung, nur aufschreiben.**
→ **`DINO_IMPROVEMENT_PLAN.md`** (Repo-Root). Basis: 4 Web-Research-Sweeps (Heads/
Losses/Vectorization/Data, alle Claims mit URLs) + lokale Evidenz. Kernbefunde:
- Lokale Analyse: DINO-MS in-scope **P=0.819 R=0.670** → RECALL ist die Lücke,
  gleichmäßig über alle Maps (nur decrepit-attic <0.5). Oracle(DINO,HEAT-ep48)=0.759,
  Typ-Routing (caves→DINO) SCHLECHTER (0.692) — Gewinner folgt nicht dem Typ-Split.
- Tversky-Flag-Konvention VERIFIZIERT korrekt (SMP: beta auf FN-Term → recall-favoring).
- Strategie: „Recall in der Maske, Precision im Graph" — recall-shaped Losses
  (Tversky 0.7 + Skeleton Recall Loss statt clDice) + Auflösung 252→518, dann
  MRF/gelernte Edge-Verification als Precision-Netz auf Graph-Ebene.
- Phase 3 (strukturell): DINOv3-ViT-L (gated, User-Lizenz nötig; kleiner ALS ViT-g
  und besser dense), UniMatch-V2-SSL auf 176k-Pool, ControlNet-Synthesedaten
  (FreeMask-Rezept), CAGE als HEAT-Nachfolger (edge-nativ, +9-11 über HEAT auf S3D).
- Ehrlich: kein Einzel-Hebel macht 0.73→0.9; Plan stapelt Phasen mit Gates.

**Nebenbei gefixt (laufende HEAT-Überwachung, nicht der DINO-Plan):** ep50-Snapshot-
Eval crashte mit `KeyError: 368` in vendor corner_to_edge (`all_combibations` deckt
nur 2–350 Corners; neue Ckpts feuern >350 auf cluttered Tiles). Fix in
`pipeline/heat_eval_uvtt.py`: Top-350 Corners nach Confidence cappen (No-op ≤350).
Stale ep50.log gelöscht → Monitor-Retry läuft mit Fix.

## 2026-07-21 (spät) — ep48-Baseline-Probe fertig: HEAT in-scope full-32 = 0.688

Der 32-Map-ep48-Baseline-Eval (Sanity/Methoden-Check auf altem ep48-Ckpt,
`heat_inscope_probe.log`) ist durchgelaufen: **MEAN HEAT P=0.758 R=0.654 F1=0.688**
(n=32). Also HEAT @ep48 (~3 FT-Epochen) noch UNTER DINO-in-scope 0.728. Bild ist
bimodal wie in der Diagnose: stark depleted-mine 0.94 / desolate-cellblock 0.92 /
sewer-town 0.92 / crypt 0.87; schwach decrepit-attic 0.32 / valley-encampment 0.29 /
old-owl-well 0.37 / confectionery 0.44. Auf Full-Corpus-Ebene ist RECALL (0.654) der
größere Drag, nicht Precision (0.758) — anders als die frühe erste-Maps-Diagnose
(die auf den schwachen Maps Precision-Probleme sah). ep50 CPU-Eval läuft gerade
(Monitor); erste 2 Maps zeigen P≈0.90 → beobachten ob Precision mit Epochen weiter
steigt. Nächster echter Vergleichspunkt: ep50/ep60-mean vs DINO 0.728.

## 2026-07-21 (Abend) — Pivot zu HEAT-in-scope (User: DINO-Long abgebrochen)

**User-Entscheid:** DINOv2-Long-Run (`wall_dino_fa_inscope_long.pt`) bei Epoche 12/18
ABGEBROCHEN (bester val Dice 0.666 @ep8, Kurve plateauierte 0.64–0.666 seit ep5 —
das ist aber MASK-Dice, entkoppelt von Graph-F1). Stattdessen jetzt HEAT-Arc.

**HEAT in-scope sauber aufgesetzt (Fix für altes polluted FA-HEAT ~0.50):**
- `dd2vtt_to_heat.py` gepatcht: neue Flags `--fa_holdout` (default fa_test.txt) und
  `--fa_exclude`. Build `corpus/heat_data_fa_inscope`:
  `--fa --fa_holdout corpus/fa_test_inscope.txt --fa_exclude corpus/fa_outscope.txt`
  → **225 Maps, 5585 train / 547 valid Crops** (real dd2vtt + FA in-scope buildings+
  caves; 32 in-scope-Test raus, 69 out-scope raus).
- Symlink `vendor/heat/data/s3d_floorplan → corpus/heat_data_fa_inscope` (ZURÜCK auf
  heat_data_fa für dd2vtt-only!).
- Training LÄUFT (setsid, OOM-retry, bs=8, warmstart `ckpts_heat_byol_full/
  checkpoint_best.pth` ep45→46): `train.py --exp_dataset s3d_floorplan --image_size 256
  --resume ... --output_dir checkpoints/ckpts_heat_fa_inscope --epochs 250 --lr_drop 200
  --run_validation --save_every 10`. Log `corpus/results/train_heat_fa_inscope.log`.
- **GOTCHA GPU-Sharing:** Gemma frisst GPU → ~10 min/Epoche (95% util contention);
  bs=8 = 9.3GB (passt in ~12.5GB frei). 250-Epochen-Cap = ~34h → NICHT auslaufen
  lassen; User-Entscheid „laufen lassen, früh stoppen": Snapshots per CPU-Eval auf
  in-scope-32 messen, bei Graph-F1-Plateau stoppen. save_every 10 → ep50,60,…
- **CPU-Eval gebaut** (`heat_eval_uvtt.py`): env `HEAT_EVAL_DEV=cpu` + Flag `--fa_list`.
  3 Bugs gefixt für CPU: (1) nn.DataParallel erzwingt cuda:0 → auf CPU bare Module +
  "module."-Prefix strippen; (2) `ResNetBackbone.train()` gibt None zurück → NICHT von
  `.eval()` reassignen, in-place mutieren; (3) MSDeformAttn hat keine CPU-Impl →
  `ms_deform_attn.py` Fallback auf `ms_deform_attn_core_pytorch` wenn `not value.is_cuda`
  (CUDA/Training-Pfad unberührt). Aufruf: `HEAT_EVAL_DEV=cpu … heat_eval_uvtt.py --ckpt
  <snap> --image_size 256 --fa_test --fa_list corpus/fa_test_inscope.txt --per_map`.
- **Zahlen @ep48 (warmstart+~3 Epochen, CPU): mean der ersten ~9 Maps ~0.66, GEMISCHT.**
  Stark: depleted-mine 0.94, crypt-of-the-talhund 0.87, cave-gallery-ab 0.81,
  barracks-and-storage 0.81, abandoned-cathedral 0.73. Schwach: decrepit-estate-attic
  0.32, briny-maze-dragon-s-den (cave) 0.36, confectionery 0.44.

**DIAGNOSE der schwachen Maps (Overlays `corpus/results/heat_weak_overlays/`, GRÜN=GT
ROT=pred):** Fehler ist **PRECISION, nicht Recall** (P 0.25–0.39 / R 0.38–0.60). HEAT
findet die echten Wände weitgehend, erfindet aber Falsch-Positive: (a) Außendächer/
-strukturen außerhalb des GT-Footprints, (b) Möbel/Bodentextur INNEN, (c) einen
Bild-Rand-Kasten (→ `drop_border_edges` leckt, härten). Höhlen: glatte Perimeter-Kurve
wird fragmentiert + Innen-Clutter halluziniert (bekannter HEAT-organisch-Fail). Bei ep48
sind das nur ~3 FT-Epochen → Clutter-Unterdrückung sollte mit mehr Training kommen
(starke Maps belegen, dass HEAT-in-scope das Niveau erreichen kann).

**Verbesserungs-Hebel (Reihenfolge):** (1) weiter trainieren + Snapshots messen, bei
Plateau stoppen; (2) `--max_corner_num` >150 (mehr Output-Vertices, v.a. Höhlen);
(3) Per-Map-Routing HEAT(buildings)+DINO(caves); (4) `drop_border_edges` härten.

**Balken bleibt bis Gegenbeweis:** DINO-FA-in-scope 0.728 (MS) / HEAT dd2vtt 0.926.

## 2026-07-20 (Nacht) — FA IN-SCOPE-Neudefinition: 0.697 auf echten Wänden; Plan DINO→HEAT auf 0.9

**Durchbruch beim Framing (User-getrieben):** Der FA-Wert 0.55 war halb echte Maps,
halb unlösbares Terrain (Sümpfe/Flüsse/Wüsten, wo „Wand" = fuzzy Sichtlinien-Entscheidung
oder nur Perimeter). User-Entscheid: organische/terrain-Maps sind NICHT im Scope.
Höhlen BLEIBEN drin (klare Fels-Kanten). Belegt per GT-Overlay-Inspektion aller 51
Held-out-Maps + edge-support/rectilinearity-Proxies (beide trennen NICHT sauber →
Klassifikation ist visuell/semantisch, nicht geometrisch).

**In-Scope-Split (Held-out, 51 → 32 IN / 2 BORDER / 17 OUT):**
- Listen: `corpus/fa_test_inscope.txt` (32), `_borderline.txt` (2, ship/canyon),
  `_outscope.txt` (17), `_buildings.txt` (23), `_caves.txt` (9).
- **Copy-Paste-Modell `wall_dino_fa_cp.pt`:** best mask Dice 0.625 (ep2, Kurve
  plateau→verworfen). Graph-F1: ALL 0.541 / IN 0.693. → CP ist KEIN Gewinn.
- **Champion `wall_dino_fa.pt` (single-scale):** ALL 0.552 / **IN-SCOPE 0.697**.
  DAS ist der aktuelle Balken. Copy-Paste bleibt verworfen.
- **HEAT zero-shot (0.926-dd2vtt-Champion, sah NIE FA):** ALL 0.409 /
  **IN 0.571 / BUILDINGS 0.614 / CAVES 0.459 / OUT 0.112.** Einzelne Buildings
  zero-shot schon 0.74–0.81 (cellblock 0.81, wooden-fort 0.78). → HEAT ist auf
  Buildings stark (dd2vtt-Heimspiel), auf Höhlen schwächer (Kurven, endlicher
  Vertex-Budget) — genau die erwartete Komplementarität.

**RUN 1 ERGEBNIS (in-scope-only Trainingsdaten, sonst Champion-Rezept 60k/6ep):**
`wall_dino_fa_inscope.pt`, mask val Dice FLACH 0.628→0.632→…→0.618 (best 0.632).
Graph-F1 in-scope: **single 0.707** (Champion 0.697 → Data-Cleanup allein +0.010),
**multi-scale 0.728** (+0.021 durch MS) → gesamt +0.031. buildings≈caves (~0.71/0.72-0.75).
**LÄUFT (Nacht 2026-07-21): LONG-RUN** `wall_dino_fa_inscope_long.pt`
(--samples 180000 = 3× Run1, bs=4 [Gemma-Speicher!], 18 val-points, KEIN Tversky
→ „länger trainieren" isoliert testen; User: Geduld, lokale Optima). Log
`train_dino_fa_inscope_long.log` (Launch-Retry-Wrapper wg. sporadischem Load-OOM).
GPU teilt sich mit Gemma-4-31B (q4_0 GGUF, ctx 96k, llama-server) → nur ~19GB frei,
daher bs=4. Wenn User ctx→32k senkt: bs=8 möglich (schneller).

**MERKNOTE Metrik:** `--epochs` = nur Val-Frequenz; `--samples` = echte Trainingslänge.
Neue Trainingsdaten via `corpus/fa_outscope.txt` (69 Maps raus) → fa_tiles 394→275.

**USER-PLAN (freigegeben): erst DINO-Pipeline auf >0.9 (in-scope), dann HEAT.**
Wenn HEAT für Höhlen zu wenig ausdrucksstark → HEAT mit MEHR Output-Vertices neu
trainieren. Out-of-scope-Maps MÜSSEN aus den Trainingsdaten raus.
Schritte: (1) 216 Train-Maps in/out klassifizieren (LÄUFT, 4 Subagents auf
Montage-Grids `scratchpad/train_mont/train_00..13.png`) → `corpus/fa_outscope.txt`;
(2) `build_real_tiles.py build_fa` um outscope-Skip erweitern, fa_tiles neu bauen;
(3) DINO-FA auf in-scope-only neu trainieren (+ recall-gewichteter Loss/Tversky,
P=0.64≫R=0.50 ist die Lücke; + Multi-Scale-Inferenz +0.015); (4) GT/Kontrast-Fixes
für gedeckelte in-scope-Maps (yuletide white-on-white, old-mill unter-gelabelt);
(5) dann HEAT auf in-scope-only fine-tunen (warm-start 0.926), Höhlen→ggf mehr Vertices.

**HW-MERKNOTE (User will Gemma ins Unified-RAM laden):** Box = GB10, ~128GB unified.
CUDA `mem_get_info` zeigt frei nur ~13GB (≈78GB Linux-Page-Cache zählt als belegt →
reclaimable, echte ~90GB verfügbar). Resident-Services (open-webui, ragflow,
gpustack/llama-box, harness) ≈29GB. **DINO ViT-g Training-Peak (bs=8, gemessen)
= ~23GB** (Weights 4.6GB). Sporadische OOM beim Model-Load = großer contiguous-Alloc
scheitert vor Cache-Eviction → mit `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
starten + retry. Für Gemma concurrent: ≤~50GB (Gemma-27B 4-bit ~16GB / 12B fp16 ~24GB
sicher; 27B fp16 ~54GB zu eng). Training-bs bei Bedarf auf 4 (~14GB) senken.



**Pivot:** MoE-Gate verworfen (Eintrag unten). User-Idee stattdessen: „FA-Tiles in
einem contrastive/paste-Lauf nutzen — non-wall-Content dazu, Wand bleibt gleich."
Faktencheck: **noch NIE contrastive/paste gemacht** (augment() war nur crop/flip/
rot/color/grid; JEPA-SSL gescheitert). FA-Objekt-Sprites Patreon-gated → aber
Distraktoren gratis aus den FA-Maps selbst (organische Nicht-Wand-Regionen).

**Online-Research (zitiert, im Chat verifiziert), Shortlist billig-zuerst:**
1. **Copy-Paste-Aug (Ghiasi CVPR'21, arxiv 2012.07177)** = die User-Idee. Zufälliges
   Einpasten von Non-Target-Clutter, Label unverändert → Netz lernt „Clutter≠Wand".
   Reiner Supervised-Loss mit unveränderter Maske reicht (KEIN teurer Consistency-/
   Mean-Teacher-Branch nötig — der ist explizit zurückgestellt). Pitfall: harte
   Paste-Kanten → als „Wand-Kante" lernbar → FEATHERN.
2. Style/Textur-Randomisierung (Geirhos ICLR'19 texture-vs-shape) gegen „gemalte
   Boden-Textur→Wand"; DINOv2 schon eher shape-biased → kleinerer Gewinn.
3. clDice→**Skeleton-Recall-Loss (ECCV'24, arxiv 2404.03010)** ~gratis, hebt Recall
   feiner GEKRÜMMTER Wände (die 0.00-Sümpfe). + Boundary-Loss.
   NICHT jetzt: volle CPS/Mean-Teacher-Consistency-Infra (teuer, erst nach 1–3).

**Umgesetzt + LÄUFT:** `pipeline/build_distractors.py` → **2766 Non-Wall-Patches**
aus FA-Maps (Crops wo Wandmaske leer, `corpus/fa_distractors/`, gitignored).
`train_seg.augment()` pastet 1–4 gefederte Ellipsen-Distraktoren pro Tile auf
BODEN (Zielregion <2% Wand → Wände nie verdeckt, Maske bleibt gültig); per Env-Var
`DISTRACTOR_BANK` opt-in (kein Effekt auf andere Trainings). Visuell geprüft (H2):
gefederte Kanten, Boden-Platzierung, Masken intakt. Retrain DINO-FA mit
Distraktoren AN → `pipeline/models/wall_dino_fa_cp.pt` (val=39 FA-holdout, 6ep,
Log `corpus/results/train_dino_fa_cp.log`, setsid/überlebt-/clear).
**BASELINE zu schlagen: FA 0.567 (single)/0.568 (MS), dd2vtt 0.894 (nicht regredieren).**
Bei Resume: Log/Prozess prüfen → beide Domänen messen → notes+commit → wenn hilft:
Style-Rand / Skeleton-Recall als nächstes; wenn nicht: berichten. Commits dieser
Runde: 22b914d, e020f17, bf3afb5, (Ceiling), 586832b (Copy-Paste-Code).

## 2026-07-20 (Ausführung) — Plan-#5 VORPRÜFUNG: MoE-Gate ist LOW-VALUE (Oracle-Decke gemessen)

Vor dem teuren Gate-Bau die MoE-Decke gemessen (per-Map-Oracle HEAT vs DINO-FA auf
BEIDEN Held-outs, echter Graph-Output). Log `corpus/results/moe_ceiling_permap.log`.

|                     | dd2vtt 6-hart | FA held-out (n=51) |
|---------------------|---------------|--------------------|
| HEAT allein         | **0.925**     | 0.409              |
| DINO-FA allein      | 0.895         | **0.567**          |
| MoE-Oracle (perfekt)| 0.942         | 0.574              |

**BEFUND: Das gelernte MoE-Gate lohnt kaum.** Ein PERFEKTER Per-Map-Router über die
zwei Experten schlägt DINO-FA-allein nur um **+0.047 (dd2vtt) / +0.007 (FA)** — und
das ist die unerreichbare Obergrenze. Ein echtes gelerntes Gate holt weniger; zudem
müsste HEAT (liefert Segmente, keine Dense-Prob) für die Pixel-Fusion rasterisiert
+ neu ge-graph't werden → HEATs saubere Geometrie ginge teils verloren → Netto real
evtl. ≈0 oder negativ. Auf FA rettet HEAT nur 4 von 51 Maps (briny-maze +0.19, sonst
<+0.05). **DINO-FA allein IST bereits das Multi-Domänen-Modell, das der Plan wollte**
(0.895/0.567): der FA-Finetune hat HEATs dd2vtt-Stärke praktisch absorbiert
(0.894≈0.925) und FA dazugewonnen. Gleiche Aussage wie „FUSION WIDERLEGT" (HEAT+Seg),
jetzt für HEAT+DINO bestätigt.

**→ USER-ENTSCHEIDUNG offen (gefragt):** Gate trotzdem bauen (explizit gewünscht;
Decke +0.047 dd2vtt) / DINO-FA als Deliverable akzeptieren + höherwertige Richtung
(FA-Recall organische Maps, oder skeleton→graph-Verlust) / leichter Domänen-Router
(kein Pixel-CNN) für die +0.047 dd2vtt. STAND: #1–#4 fertig, #5 pausiert bis Antwort.

## 2026-07-20 (Ausführung) — Plan-#4 Multi-Scale: +0.015 (Inferenz-Pyramide), ASPP zurückgestellt

Multi-Scale-INFERENZ zuerst getestet (billig, kein Retrain): DINO-FA-Experte auf
mehreren long_edge-Skalen laufen lassen, prob-Karten fusionieren, dann build_graph.
Neues Skript `pipeline/graph_eval_dino_ms.py`.
- scales {768,1024,1536}: **FA held-out F1 0.568** (P 0.665 / R 0.516) — +0.015 über
  Single-Scale 0.553, GESCHENKT (nur Inferenz). Gewinn ist Precision (0.62→0.67):
  Mittelung über Skalen unterdrückt skalen-spezifische Falsch-Wände.
- scales {1024,1536,2048} (feiner): 0.563 — SCHLECHTER. Höhere Auflösung hilft
  nicht. Logs `corpus/results/dino_fa_ms.log`, `…_ms2.log`.

**ENTSCHEIDUNG (evidenzbasiert): ASPP-Decoder-Retrain (#4b) ZURÜCKGESTELLT als
low-ROI.** Begründung: die Inferenz-Pyramide hat den Multi-Scale-Nutzen schon
billig geholt (+0.015), und feinere Skalen halfen NICHT — die organischen Maps
(forest-river/swamp = 0.00) scheitern SEMANTISCH, nicht an der Auflösung. Skala ist
also nicht der FA-Flaschenhals. ASPP bliebe ein optionaler Hebel, aber der
höchste-Wert-Schritt ist jetzt #5 (das gelernte MoE-Gate = Kern-Auftrag des Users).
Multi-Scale-Inferenz {768,1024,1536} wird als DINO-Inferenzmodus übernommen.

## 2026-07-20 (Ausführung) — Plan-#3 ERLEDIGT: DINO-FA-Experte (FA 0.553, dd2vtt 0.894)

**DURCHBRUCH FA-Domäne.** DINO ViT-g auf donjon(8k)+dd2vtt+FA fine-getunt →
`pipeline/models/wall_dino_fa.pt`. Ergebnisse (echter Graph-Output):
- **FA held-out (n=51): F1 0.553** (P 0.619 / R 0.525). Von zero-shot 0.321 →
  **+0.232**; Recall 0.253 → 0.525 (mehr als verdoppelt). **Bester FA-Einzel-Wert**
  (schlägt Seg-U-Net 0.505 und HEAT 0.409).
- **dd2vtt 6-hart: F1 0.894** (P 0.838 / R 0.962). Original-DINO-Graph war 0.896 →
  praktisch ERHALTEN (−0.002). D.h. der FA-Finetune hat dd2vtt NICHT kaputt gemacht.
- Ein einziger Experte, gut auf BEIDEN Domänen. Logs
  `corpus/results/dino_fa_ft2_holdout.log`, `…_dd2vtt.log`.

**KOMPLEMENTARITÄT für MoE bestätigt:** dd2vtt HEAT 0.926 > DINO-FA 0.894;
FA DINO-FA 0.553 > HEAT 0.409. Gate soll dd2vtt→HEAT, FA→DINO-FA routen — genau
der User-MoE-Aufbau. Per-Domäne-Oracle-Decke also ~max(0.926 / 0.553).

**METHODEN-BUG in `train_dino.py` gefunden + gefixt (committet).** Val-Set war
DONJON-only (`va=files[:nval]`), also selektierte Best-Tracking den DONJON-nächsten
= WENIGST-FA-adaptierten Checkpoint (ep1). Erster FT-Lauf: donjon-val fiel
0.409→0.324 über die Epochen — täuschte „Degradation" vor, war aber nur Drift WEG
von donjon HIN zu real/FA. Der ep1-Checkpoint gab auf FA schon 0.538. Fix: FA-val-
Split aus `fa_tiles` (39 Tiles, nach Map-Slug sortiert=map-kohärent, DISJUNKT von
fa_test) als Selektions-Signal; ALLE donjon bleiben im Training (User-Vorgabe).
Re-Run: FA-val Dice 0.583/0.579/**0.618**(ep3)/0.611/0.561/0.586 → ep3 gewählt →
FA-Test 0.553. (ep1-0.538-Modell in scratchpad gesichert.)

**Reihenfolge:** #1+#2+#3 fertig. Nächste: #4 Multi-Scale (DINO-Engpass SZ=252 —
erst billige Multi-Scale-INFERENZ testen, bevor Architektur+Retrain), dann #5 Gate.

## 2026-07-20 (Ausführung) — Plan-Schritte #1+#2 gemessen (Seg-2x, DINO-zero-shot FA)

Nach /clear den Plan (Eintrag unten) abgearbeitet. GPU seriell (1 Karte).

**GOTCHA (Zeit gekostet): 2×-Seg-Training starb bei epoch 5/12.** Kein Traceback,
kein OOM (98 GB RAM frei), extern gekillt — mit hoher Wahrscheinlichkeit der
Session-Teardown beim `/clear`, weil der Vorlauf NICHT detached war. Fix: neu
gestartet mit `setsid` + venv-`python -u` (unbuffered) + `< /dev/null`, sodass er
Teardown überlebt und keine Logzeilen verliert. ⚠️ Erste setsid-Variante scheiterte
mit `python: command not found` (fresh setsid-Shell hat kein venv-PATH) → immer
`/home/spark1admin/draw_maps/.venv/bin/python` absolut aufrufen. Alter ep6-Checkpoint
(val Dice ≥0.475) nach scratchpad gesichert vor Neustart.

**#1 — 2×-Seg fertig (12ep, samples 240k): best val Dice 0.544** (ep11), vs. clean-
Baseline 0.516 (+0.028 auf Masken-Ebene). ABER **echter Graph-Output auf FA
held-out (n=51): F1 0.505** (P 0.548 / R 0.495), excl-deg ≈0.531. Clean-Baseline
war 0.507 / excl-deg 0.536. → **NEGATIVERGEBNIS: Mehr Seg-Training hilft dem
Deliverable NICHT.** Die Masken-Verbesserung (+0.028 Dice) propagiert nicht durch
`build_graph`. Bestätigt: der Skelett→Graph-Schritt ist der Flaschenhals (Plan-
Next-Step #2), nicht die Maskenqualität. Log `corpus/results/seg_fa_graph_holdout_2x.log`.
Checkpoint `pipeline/models/wall_graph_fa_clean2x.pt` (ep11-best).

**#2 — DINO ViT-g (dd2vtt-trainiert, `wall_dino_vitg.pt`) zero-shot auf FA:
F1 0.321** (P 0.519 / R 0.253), n=51. Die fehlende Zahl aus dem Plan. Muster:
**hohe Precision, eingebrochene Recall (0.25)** — auf clean-dd2vtt trainiertes DINO
ist auf FA konservativ: saubere Innenräume top (briny-maze 0.94, sewer-town 0.79,
wooden-fort 0.74, crypt 0.76), aber **0.00 auf JEDER organischen/Außen-Map**
(forest-river a+b, gloomy-swamp, swamp-b, jungle-rope-bridge, thicket-road, winter-
lake, hag-tree, ilvaash). Deutlich unter Seg (0.505). Log
`corpus/results/dino_fa_zeroshot.log`. GOTCHA: erster Lauf CUDA-OOM, weil direkt
nach Training-Ende gestartet (Training gab VRAM auf GB10-Unified-Mem noch nicht
frei); Retry nach GPU-frei OK. `model()` ist Singleton (kein Per-Map-Leak, geprüft).

**Zwischenfazit für MoE:** Auf FA trägt Seg (Recall-stark, 0.505) die Basis, DINO
(Precision-stark, Recall-schwach) ist im aktuellen Zustand KEIN FA-Experte — genau
deshalb Plan-#3: DINO auf donjon(cap)+dd2vtt+FA fine-tunen, um FA-Recall zu heben.
LÄUFT (siehe unten). Reihenfolge #3→#4→#5 unverändert.

## 2026-07-20 (Plan) — GELERNTES MoE(HEAT,DINO) + MULTI-SCALE, ALLE DOMÄNEN (User-Auftrag)

User-Entscheidung: **alle Domänen abdecken** (dd2vtt + FA + …), **gelerntes MoE-Gate**,
**donjon bleibt in JEDEM Training** (170k Tiles, damit dd2vtt-Erkenntnisse bleiben),
Architektur **aufbohren + Multi-Scale**. Ausgangslage: HEAT 0.926 (dd2vtt)/0.409 (FA);
Seg-U-Net 0.507 (FA). WICHTIG (heute belegt): HEAT↔Seg-Oracle auf FA nur +0.017 →
auf FA trägt HEAT fast nichts; die Komplementarität HEAT+DINO ist eine dd2vtt-Sache
(Oracle ~0.94). Ein MoE über ALLE Domänen ist daher sinnvoll: HEAT trägt dd2vtt,
DINO/Seg trägt FA; das Gate lernt die Zuordnung pro Pixel/Region.

**Architektur (Ziel):** zwei Experten → je eine Wand-Wahrscheinlichkeitskarte →
Gating-CNN über `[Bild, prob_HEAT, prob_DINO]` → per-Pixel-Gewichte → fusionierte
Wandkarte → `build_graph` → **piecewise-linear-Graph (H4 gewahrt)**. Gate wird PRO
PIXEL auf dem vollen Pool trainiert (Supervision = Per-Tile-GT-Übereinstimmung je
Experte) → Datenmenge unkritisch (kein Map-Level-Overfit).
- **Experte HEAT**: Grundriss (Ecken+Geraden), stark dd2vtt.
- **Experte DINO ViT-g**: Segmentierung (kurvenfähig), FA/organisch. Fine-Tune auf
  donjon(cap)+dd2vtt+FA. `train_dino.py` gepatcht: `--real` jetzt komma-getrennt
  (FA-Tiles einbeziehbar); donjon via `--donjon_cap` (default 8000, bewusst
  gedeckelt für teures ViT-g bs8 — donjon bleibt drin).
- **Multi-Scale**: DINO sieht Kacheln nur bei SZ=252 (Hauptengpass; forward() kann
  aber beliebiges SZ). Hebel: (a) ASPP/dilated-Decoder (Filter mehrerer Dilations-
  raten = „mehrere Auflösungen", DeepLabV3+-Stil); (b) Multi-Scale-Inferenz
  (Pyramide, prob-Karten fusionieren). Erst durch build_graph-Fix voll nutzbar.

**Reihenfolge (seriell, 1 GPU):**
1. [läuft] 2×-Seg (`wall_graph_fa_clean2x.pt`, samples 240k/12ep) fertig → auf FA
   messen (echter Graph-Output). Prüft, ob „mehr Training" der Seg-Familie hilft.
2. DINO-Graph (`wall_dino_vitg.pt`, dd2vtt-trainiert) zero-shot auf FA messen
   (fehlende Zahl; graph_eval_dino --fa_test).
3. DINO auf donjon(cap)+dd2vtt+FA fine-tunen (der FA-Experte) → FA + dd2vtt messen.
4. Multi-Scale-Decoder (ASPP/höheres SZ) → messen.
5. Gating-CNN trainieren → auf BEIDEN Held-outs (dd2vtt-6-hart + FA-51) vs. Experten
   + Oracle.

## 2026-07-20 (Fortsetzung) — SAUBERE FA-BASELINE etabliert (nach Tile-Rebuild)

Nach dem Re-Harvest (267 Maps, 0 schwarz) die versprochenen Schritte 1–2 gemacht.

**Schritt 1 — Tiles neu gebaut.** `corpus/fa_tiles/` gelöscht + neu erzeugt
(`build_real_tiles.py --only fa --out corpus/fa_tiles`) → **394 Tiles** aus
sauberen Bildern (build_fa schließt fa_test korrekt aus, verifiziert). Alte Tiles
(07-19, enthielten ~13 schwarze Trainingsmaps) sind weg.

**Schritt 2 — EHRLICHE Baseline auf bereinigtem 51-Map-Held-out.**
- **HEAT/BYOL 0.926-Modell (sah nie FA), zero-shot: F1 0.409** (n=51, image_size
  256). Vorher auf verschmutztem Test 0.360 → Bereinigung +0.049. Ohne die 3
  degenerierten Maps (≤4 GT-Wände = reiner Kartenrand: forest-town-bridges,
  red-rock-gully, winter-lake): **F1 0.432** (n=49). Log:
  `corpus/results/heat_fa_clean_holdout.log`.
- Verteilung stark BIMODAL: 17 Maps <0.2 (organisch/außen), 9 Maps >0.7 (sauberes
  Innen: desolate-cellblock 0.81, wooden-fort-old 0.78, eternal-vale-cemetery
  0.75). Bestätigt Diagnose.
- ZWEI HEAT-Fehlermodi belegt: (a) **helle Hintergründe** — `yuletide-lodge`
  (imgmean 224, Schnee, 228 GT-Wände) → HEAT malt 0 Segmente (braucht dunkle
  Wand-Strokes); (b) **organische/gekrümmte** Grenzen (forest-river 0.14–0.22,
  gloomy-swamp 0.01).
- **Seg-U-Net neu auf SAUBEREN Tiles** (`wall_graph_fa_clean.pt`, donjon+real+
  fa_tiles, 21% real, real_mul 65, 6ep, best val Dice 0.516 — stieg noch, mehr
  Epochen könnten helfen). FA held-out:
  - **Masken-Level (obere Schranke, --fast): F1 0.559** (excl-deg 0.587), vorher
    dreckig 0.511. Log `corpus/results/seg_fa_clean_holdout.log`.
  - **ECHTER Graph-Output (piecewise-linear, KEIN --fast): F1 0.507** (excl-deg
    0.536). build_graph kostet ~0.05 ggü. Masken-UB. Log
    `corpus/results/seg_fa_graph_holdout.log`.

**ERGEBNIS: Seg (0.507 echt / 0.536 excl-deg) SCHLÄGT HEAT (0.409 / 0.432) auf FA
und liefert den vom User geforderten piecewise-linear-Output.** Seg gewinnt 36
von 48 Maps, HEAT nur 4 — genau die organischen Außen-Maps (gibbet 0.08→0.76,
great-cavern 0.29→0.78, lava-cavern 0.16→0.58). Overlays geprüft (H2):
great-cavern (Höhlengrenze als kurze Geraden, eng an GT), desolate-cellblock
(Zellenstruktur erfasst, leichte Übersegmentierung aus Bodentextur).

**⚠️ PRIORITÄTEN-UMKEHR (durch saubere Daten): FUSION IST NICHT MEHR DER HEBEL.**
Per-Map-Oracle max(HEAT,SEG) = 0.604, nur **+0.017** über Seg allein (Seg ist
fast eine Obermenge von HEAT). Die frühere These „HEAT↔Seg-Fusion höchste Decke"
ist empirisch widerlegt. Der Hebel ist der SEG-WEG SELBST: (a) mehr Epochen (Dice
stieg noch), (b) Style-/Textur-Aug gegen gemalt↔flach-Bias, (c) Skeleton-Recall-
Loss, (d) build_graph-Verluste (0.559→0.507) reduzieren (bessere Skelett→Graph).

**BUILD_GRAPH-HANG GEFIXT (`graph_infer.py`).** Zwei quadratische Hotspots:
(1) `snap()` war O(n) pro Vertex → O(V²); jetzt Raum-Hash-Grid (3×3-Zellen,
O(1) amortisiert). (2) `merge_collinear` brach nach JEDEM Merge ab + baute deg
neu → O(E²); jetzt In-Place-Adjazenz + Worklist (~linear). Messung warehouse@2048:
**>110s Hang → 0.7s**; @1536 11s→0.4s. Output BIT-IDENTISCH vor/nach (nodes/edges/
maskpx exakt gleich auf 3 Maps) — reiner Speedup. Damit ist der echte piecewise-
linear-Output auf Voll-Auflösung lieferbar; `--fast` nicht mehr nötig.

DEGENERIERTE-MAPS-BEFUND: nur 3 von 51 Held-out haben ≤8 GT-Wände (reiner Rand);
diese aus der FA-Metrik nehmen ist gerechtfertigt (F1 dort = Rauschen).

### NEUE NÄCHSTE SCHRITTE (Reihenfolge, ersetzt die Fusion-Priorität)
1. **Seg-Modell hochtrainieren**: mehr Epochen (Dice stieg noch bei ep6) +
   Style/Textur-Aug (gemalt→flach) — der klarste Hebel, da Seg dominiert.
2. Skeleton→Graph-Verlust (0.559→0.507) angehen: bessere Skelettierung/
   Simplify-eps, damit der echte Output näher an die Masken-Schranke kommt.
3. yuletide-lodge-Klasse (heller Schnee-BG): Seg-Maske 0.28 → Graph 0.03 (build_
   graph zerfällt auf fragmentierter Maske) — untersuchen.

## 2026-07-20 — FA-DOMÄNE: Diagnose, Seg-Weg, DATEN-BUG gefunden (schwarze Bilder)

Ziel (User): FA-Domänen-F1 über 0.5 heben; 20% der FA-Maps als echtes Held-out.
KLARE ERKENNTNISSE dieser Session (nach `/clear` hier weiterlesen):

**Setup.** 20% FA held-out = `corpus/fa_test.txt` (55 Maps, deterministisch jede
5.). Training schließt sie aus (0 Leck verifiziert). Eval-Skripte haben jetzt
`--fa_test` (heat_eval_uvtt, graph_eval_uvtt, graph_eval_dino).

**Baselines auf 55 FA held-out (Achtung: noch MIT 7 schwarzen Bildern gemessen,
also zu niedrig!):**
- HEAT/BYOL 0.926-Modell (sah nie FA), zero-shot: **F1 0.360**.
- HEAT auf FA weitertrainiert (Warm-Start vom 0.926): FA 0.36→~**0.50** (Peak
  früh ~ep53), dd2vtt 0.926→0.88–0.91. MEHR EPOCHEN HELFEN NICHT.
- Seg/Graph-U-Net auf FA trainiert (`wall_graph_fa.pt`), Masken-Level (obere
  Schranke, `--fast`): FA **0.511** (Baseline ohne FA 0.364; +0.147 durch FA).
  dd2vtt 6-hart Masken-Level 0.660.

**DIAGNOSE HEAT-Versagen (belegt via Overlay):** HEAT scheitert an AUSSEN-/
ORGANISCHEN Maps (Sümpfe/Flüsse/Seen/Höhlen) — malt ein RECHTECKIGES RASTER über
z.B. den zugefrorenen See (`winter-lake` F1 0.00), weil sein Ecken+Geraden-
Floorplan-Prior keine gekrümmten Naturgrenzen kann. ABER: das Seg-Modell (kann
Kurven) erreicht auch nur ~0.51 und scheitert an DENSELBEN Maps → Architektur
allein war NICHT die Antwort.

**⚠️ DATEN-BUG (der eigentliche Haupthebel, TEILWEISE GEFIXT):** 20 von 274 FA-
Bildern waren SCHWARZ/kaputt. Ursache: viele Premium-Maps benennen die volle
Karte `*-gridless-*.webp` / `*_Gridless_*.webp`, mein `pick_bg_file` suchte nur
`bg.webp` → Fallback-Compositing ergab Schwarz. 7 der 20 lagen im 55-Map-Test →
scoren auto ~0 und drücken alle obigen Zahlen; ~13 vergifteten das Training.
`abandoned-cathedral` (saubere Kathedrale!) bekam nur wegen schwarzem Bild 0.00.
FIX in `fa_harvest.py`: `pick_bg_candidates()` bevorzugt `gridless`-Vollkarten
(größte zuerst), Helligkeits-Guard `_black()` (near-black → nächster Kandidat →
Composite → sonst Map verwerfen). **Re-Harvest ABGESCHLOSSEN: 267 Maps, 0 schwarz.**
13 der 20 recovered (jetzt `via=single`), 12 korrekt verworfen (nur Nacht-/
lightless-Variante vorhanden). fa_test: 51 von 55 Slugs noch vorhanden (4 waren
night-only → Eval überspringt fehlende Dateien automatisch, ist ok).

**GEDANKENFEHLER-KORREKTUR:** Die 0.51/0.49 sind auf verschmutztem Test gemessen.
Nach sauberem Re-Harvest neu messen — echte Zahlen dürften spürbar höher liegen.
Manche Natur-Maps sind zudem degeneriert (winter-lake hat nur 4 GT-Wände = quasi
Kartenrand) → F1 dort verrauscht; ggf. aus Eval nehmen/kennzeichnen.

**build_graph HÄNGT** auf großen dichten organischen FA-Masken (6h CPU-Hang, GPU
0%). Deshalb `--fast` (Masken-Level Mittellinien-F1, überspringt build_graph) in
graph_eval_uvtt. FÜR ECHTEN piecewise-linear-Output muss build_graph skalierbar
gemacht werden (User besteht auf Geradenstück-Graph als Output; Segmentierung ist
nur die INTERNE Repräsentation — das ist ok).

### NÄCHSTE SCHRITTE (Reihenfolge)
1. Re-Harvest fertig? → `python - <<black-check>` (siehe unten); Ziel: 0 schwarz,
   ~274 Maps. `corpus/fa_tiles/` NEU bauen (`build_real_tiles.py --only fa --out
   corpus/fa_tiles`) — die alten Tiles enthalten ~13 schwarze Trainingsmaps.
2. HEAT + Seg-U-Net auf BEREINIGTEM 55-Held-out neu messen (Seg mit `--fast`).
   Ehrliche FA-Baseline etablieren.
3. build_graph skalierbar fixen (echter Geradenstück-Output auf großen Maps).
4. Dann Hebel (aus 3 Recherche-Reports dieser Session, s. Memory): (a) masken-
   erhaltende Style-/Foto-Augmentation gegen TEXTUR-BIAS (gemalt vs flach); (b)
   Skeleton-Recall-Loss (clDice-Upgrade) + cbDice; (c) HEAT↔Seg OUTPUT-FUSION
   (Segment-Graphen kalibrieren+mergen, MoCaE) — höchste Decke, kann Oracle
   übertreffen; ZUERST 2-Experten-Per-Map-Oracle auf FA berechnen (dd2vtt-Oracle
   nur ~0.014, FA-Oracle vermutlich groß). MoE/Router: einfacher Confidence-/
   Style-Router schlägt schweres gelerntes Gate bei dieser Datenmenge.

### Black-Check (nach Re-Harvest laufen lassen)
```
python - <<'PY'
import glob,os,sys,numpy as np; sys.path.insert(0,"pipeline"); from uvtt import load
bad=[f for f in glob.glob("corpus/fa/*.dd2vtt")
     if (lambda im: im is None or im.mean()<8 or (im.max(2)<20).mean()>.97)(load(f)["image"])]
print(len(glob.glob("corpus/fa/*.dd2vtt")),"maps,",len(bad),"black:",[os.path.basename(b) for b in bad])
PY
```

### Checkpoints/Artefakte dieser Session
- `pipeline/models/wall_graph_fa.pt` — Seg-U-Net auf donjon+dd2vtt-real+FA (real_mul
  65), Masken-FA 0.511. (Auf verschmutzten Tiles trainiert → nach Tile-Rebuild neu.)
- `vendor/heat/checkpoints/ckpts_heat_byol_fa_cont` — HEAT auf ALLEN 274 (inkl.
  Test → KONTAMINIERT, nicht für Eval nutzen). Sauberer Ausgang bleibt
  `ckpts_heat_byol_full/checkpoint_best.pth` (0.926, sah nie FA).
- `corpus/fa_test.txt` — 55 Held-out-Slugs. Premium-userId (has_premium bis
  2026-08-19): `23cfe67f-7e2c-4444-af9d-f57084819085`.
- vendor/heat-Patches (git-ignored!): `train.py --save_every N` (Snapshots),
  `arguments.py`. data-Symlink `vendor/heat/data/s3d_floorplan → corpus/heat_data_fa`
  (NICHT mehr baseline heat_data — für dd2vtt-only-Training zurückzeigen!).

## 2026-07-19 — NEUE DATENQUELLE: Forgotten-Adventures-Battlemaps als Wall-GT (Phase A fertig)

User gab Patreon-Zugang für FA. Statt Patreon-Login (nicht automatisierbar,
ToS): **öffentliches Repo + öffentliche API** ausgenutzt.
- Walls: `github.com/Forgotten-Adventures/FA_Battlemaps`, `packs/_source/maps/*.json`
  (286 Foundry-v13-Szenen, handgesetzte Wall-Docs `c:[x1,y1,x2,y2]` + Türen).
- Bilder: API `api.forgotten-adventures.net` — `list` (282 Maps: 87 Free/195
  Premium) → `list-files` → `get-file` gibt signierte S3-URL. **Free braucht KEIN
  Auth** (userId leer → 200); Premium → 401.
- **Phase A DURCH: 87 Free-Maps → `corpus/fa/*.dd2vtt`, 20.901 Wandsegmente,
  399 Türen, 0 Fehler.** Harvester `pipeline/fa_harvest.py`.
- **Phase B DURCH: +187 Premium-Maps** (von 195; 8 verloren: 3×HTTP400,
  5×no-image). User autorisierte OAuth-uuid (has_premium bis 2026-08-19).
  **Gesamt 274 Bild+Wall-Maps.** Overlays Premium (mushroom-inn) exakt.
- **Phase D LÄUFT: Fortsetzung vom 0.926-Checkpoint** (User-Wunsch: Warm-Start
  statt neu), `--resume ckpts_heat_byol_full/checkpoint_best.pth` ab Epoche 46,
  auf allen 274 FA-Maps (`dd2vtt_to_heat.py --fa` → 8810 Crops, 7.5× Baseline
  1169). output=ckpts_heat_byol_fa_cont. Baseline mit heat_eval_uvtt reproduziert:
  F1 0.926 (void-town 0.80 schwächste). Symlink data/s3d_floorplan→heat_data_fa.

Koordinaten (H7): Walls in Foundry-GEPADDETEM Canvas. `pixel=(canvas−pad)·scale`,
`pad=ceil(padding·dim/grid)·grid`, `scale=img/scene`. FALLE: manche Bilder in 2×
Szenenauflösung (Skala anwenden!). Gesplittete Maps (BG1..BGn statt gemergter
`*_BG.webp`) → **Compositing nur der Basis-Tiles** (elev≤0, keine Occlusion);
FG-Dächer/Laub WEGLASSEN, sonst verdecken sie Wände in der GT. Overlays geprüft
(H2): tomb-of-horrors, feywild (2×), gibbet + wave-echo (composite) exakt.
Bilder © FA → NICHT committen (`corpus/fa/` in .gitignore); reproduzierbar.

Idee (User): FA-Objekt-Tiles als Non-Wall-Paste-Augmentation (Clutter drauf,
Walls unverändert) → Robustheit/Precision. FA-Battlemaps liefern keine EINZEL-
Objekte (in BG/FG gebacken); FG-Tiles (transparent) als Clutter-Quelle nutzbar.
Nächste Schritte: Phase B (Premium via userId), Phase C (Paste-Aug), Phase D
(HEAT/Graph retrain + Eval auf dd2vtt-Benchmark vs. 0.926).

## 2026-07-18 — SSL-ERGEBNISSE: HEAT/BYOL 0.926 (NEUER BESTWERT), DINO/JEPA scheitert

Volle Kette durch (großer SSL-Pool 176k = 144k donjon + 633 gemalte ×50, 18%).
GEGENSÄTZLICHE Ergebnisse der beiden SSL→Finetune-Zweige:

**HEAT/BYOL = ERFOLG, NEUER BESTWERT F1 0.926** (P=0.888 R=0.973), vorher 0.908.
BYOL-vortrainierter resnet50 (train_byol, 176k Pool) → inject → HEAT-Finetune
300ep. Sauberer A/B: identischer Lauf wie das 0.908-Modell, NUR Backbone-Init
BYOL-auf-Domäne statt ImageNet. Per Map vs HEAT-ImageNet(0.908):
road-side 0.81→**0.92**, festival 0.82→**0.91** (große Gewinne), void-town
0.89→0.80 (einzige Regression), goblin/desert/little-fish unverändert
(0.95/0.98/0.99). Overlay road-side geprüft (H2): Gasthaus+Räume sauber, 1
Streulinie. Checkpoint: vendor/heat/checkpoints/ckpts_heat_byol_full/
checkpoint_best.pth. → BYOL-Domänenanpassung des CNN-Backbones WIRKT.

**DINO/JEPA = MISSERFOLG, F1 0.362** (P=0.44 R=0.37; großer Pool half ggü.
383-Collapse 0.209, aber weit unter Baseline 0.896). JEPA-Loss fiel wie beim
Collapse schnell auf ~0.11-Plateau — der große Pool hat es NICHT behoben →
Ursache ist das REZEPT, nicht die Datenmenge. Wahrscheinlich: nur last-6 blocks
trainierbar + EMA über ganzes Netz + kein Collapse-Schutz (I-JEPA verlässt sich
auf Skalierung/Datenvielfalt, die wir nicht haben). BYOL funktioniert, weil es
BN-Collapse-Schutz + vollen Backbone + sanften ImageNet-Start hat.
LEHRE: JEPA für Domänen-SSL auf kleiner Sammlung fragil; BYOL robust.
DINO/JEPA-Fix (VICReg-Reg, nur last-2, EMA-mom↑) = niedriger ROI, da DINO-
Baseline 0.896 < HEAT/BYOL 0.926 ohnehin. Zurückgestellt.

Gesamtverlauf F1: CV 0.22 → … → ResNet-Graph 0.74 → DINO-Graph 0.90 →
HEAT-ft 0.908 → **HEAT/BYOL 0.926**.

## 2026-07-17 — SSL→Finetune-Pipeline (BEIDE Zweige) läuft; ~20h durch Orchestrierungsfehler verloren

GOTCHA (teuer, ~20h): Orchestrator-Skript hatte als Stufe 0 eine Warteschleife
`while pgrep -f "train_jepa.py"; do sleep 120`. Meine eigenen Monitoring-Watcher
(until-loops) enthielten „train_jepa.py" in ihrer Kommandozeile → der
Orchestrator-pgrep matchte DIE (Selbstmatch, exakt der CLAUDE.md-pgrep-Gotcha)
→ Stufe 1 wurde nie erreicht, obwohl JEPA um 21:28 fertig war. FIX: Orchestrator
per PID gekillt, neu gestartet OHNE Warteschleife (JEPA-ckpt existiert eh),
direkt Stufe 1. LEHRE: Orchestrator-Warteschleifen NIE auf pgrep von Datei-
namen, die auch in Beobachter-Kommandos vorkommen — auf Artefakt/Logzeile warten.

**ERGEBNIS DINO-Zweig NEGATIV — JEPA hat den Backbone KOLLABIERT:**
wall_dino_vitg_jepa.pt: MEAN P=0.211 R=0.265 **F1=0.209** (vs 0.896 ohne JEPA),
alle 6 Maps 0.06–0.36, best val Dice 0.390 (<0.436 hub-init). Diagnose:
Representation Collapse — JEPA-Loss stürzt 0.68→0.12 @step1500 und plateaut
(Target-Features degenerieren, Predictor sagt trivial vorher). URSACHE
wahrscheinlich DATENMENGE: I-JEPA ist für ImageNet (~1.3M) gebaut; 383 Bilder ×
6000 steps = jedes Bild ~250× → Collapse. Auch Setup-Faktoren (nur last-6 + EMA
über alle; EMA-mom 0.996 steigt bei 6000 steps zu langsam) begünstigen es.
LEHRE: naives continued-JEPA auf kleiner Domänen-Sammlung verschlechtert einen
starken vortrainierten Backbone. Fix-Ideen falls Wiederaufnahme: viel sanfter
(nur last-2 auftauen, LR 5e-5, EMA-mom→0.999+, weniger steps/early-stop auf
Feature-Varianz), oder Collapse-resistente SSL (DINO/iBOT-Loss mit Centering),
oder SSL nur als AUXILIARY neben supervised (Multi-Task) statt sequenziell.

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
