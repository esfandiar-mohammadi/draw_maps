# CLAUDE.md — draw_maps: automatic wall drawing for Foundry VTT

> ⏩⏩⏩ **RESUME HERE — Stand 2026-07-24 spät: PROJEKT DEPLOYMENT-FERTIG, umbenannt,
> auf GitHub. Nach `/clear` ZUERST diesen Block + notes.md TOP-Eintrag.**
>
> **PRODUKTNAME: „Wall Annotation Companion"** (Modul-id `wall-annotation-companion`
> v2.2.0) — NICHT mehr „Auto Wall Companion (ML)" (das war Upstream-Name-Kollision).
> **GitHub (privat):** `https://github.com/esfandiar-mohammadi/draw_maps`, branch
> `main`, Token in `~/.git-credentials` → pushen geht direkt. **Doku = README.md**
> (INSTALL.md gelöscht); DEPLOYMENT.md = Modell/Qualität; DISTILL_PLAN.md = Distill.
> **install.sh** (Repo-Root) = vollautonomer, resumierbarer Arch-Installer: zieht das
> Modell automatisch von http://mohammadi.eu/dateien/wall_student_convnext_tiny.onnx,
> baut venv, systemd-Service, installiert das Foundry-Modul LOKAL (findet Foundry-
> Data-Dir selbst), self-test. Details: notes.md TOP-Eintrag.
> **🆕 2026-07-31: ERSTER ECHTER ZIEL-LAUF FAND STATT UND SCHEITERTE.** Das Ziel
> fährt **Foundry in DOCKER** — der Installer kannte Container gar nicht (nur nativ-
> lokale Pfade) → „keine Rechte auf das Foundry-Docker". **Gefixt + getestet**
> (install.sh: neuer Step `foundry` host-vs-docker, `docker cp`-Route mit chown auf
> die Container-uid ohne sudo, Container-Erkennung via `/proc/<pid>/cgroup` OHNE
> Docker-Zugriff, `need_user_action()`-Pause (exit 4) mit `usermod -aG docker` +
> „aus- und wieder einloggen", 3 sichtbare Stages, `--module-only`/`--service-only`/
> `--docker-container`, container-sicheres `--uninstall`). Regressionstest
> `tools/test_install_module.sh` = 51 Assertions mit ECHTEN Containern, alle grün.
> Details: notes.md TOP-Eintrag; [[foundry-in-docker-on-target]]. Merke: das Modul
> ruft den Service aus dem **Browser** → `localhost:8177` bleibt korrekt, kein
> Port-Expose/Tunnel nötig (README §C.6).
> **▶️ OFFEN: der User meldete „One error was …" → es gab MEHRERE Fehler; nur der
> Docker-Fehler ist gefixt. Vom Ziel gebraucht: `~/draw_maps/.install_state/install.log`
> bzw. Terminal-Ausgabe.** Push zu GitHub = ask-first (noch nicht gepusht).
> pacman/systemd/Vulkan/echtes root laufen auf der Ubuntu-aarch64-Devbox weiter NICHT.
>
> **── Deployment-Fakten (weiter gültig) ──**
> **ConvNeXt-Tiny (0.765 @wall_thr0.5, 32M) ist der Deployment-DEFAULT**
> (ONNX/CPU). MobileNetV3 (0.741 @thr0.4, 6.7M) = dokumentierter Fallback + einziger
> ncnn/Vulkan-Pfad. Kapazität war die Decke (EfficientNet-B4 20M=0.740 → Architektur,
> nicht Params); besserer Teacher transferiert kaum (+0.018 Teacher → +0.003 Student).
> [[distill-student-capacity-ceiling]] [[vectorizer-border-filter-recall]].
>
> **Was gemacht wurde (Details notes.md OBERSTER Eintrag):**
> 1. **ncnn/Vulkan bleibt MobileNetV3-only** — ConvNeXt konvertiert NICHT nach ncnn:
>    pnnx-Decoder-Miscompile (`convrelu_6` 3×3-Conv → `inf`, all-NaN; fp16=fp32 gleich
>    kaputt; auch via TorchScript-Route). Sauber bisektiert. Kaputte .ncnn-Dateien
>    entfernt. Vulkan war optionaler Speed-Pfad; ConvNeXt-CPU (~2-2.5s Ryzen) reicht.
> 2. `wall_service.py`: `--wall_thr` (def 0.5) → `build_graph`, Default-`--model`
>    →ConvNeXt-onnx, `/health` nennt wall_thr. (build_graph-Default bleibt 0.4.)
> 3. `tools/run_wall_service.sh`: → ConvNeXt-onnx.
> 4. E2E beide Backends grün: ConvNeXt/ONNX 283 Wände/0.84s, mbv3/ncnn 173/0.59s
>    (testmap.png 1396×2048). In-Game-Forge nicht wiederholt (architektur-agnostisch).
> 5. DEPLOYMENT.md + INSTALL.md auf ConvNeXt-Default umgestellt (+ ncnn-only-Warnung).
>
> **▶️ BEI „continue" = OPTIONALE KÜR (kein offener Pflichtschritt):** ConvNeXt-Small
> (54M) / DINOv2-ViT-S als evtl. stärkerer Student; oder Teacher-Phase-2/3 (lohnt
> für Student kaum, belegt). User fragen was priorisiert wird.
>
> **Modell-Bestwerte aktuell (in-scope-32 graph-F1, frame-aware Vektorisierer):**
> Teacher DINO 0.786 (Phase1, @thr0.7) · **Student ConvNeXt-Tiny 0.765 (@thr0.5, NEU)**
> · Student MobileNetV3 shipped 0.741 (@thr0.4). GRATIS-Gewinn dieser Session:
> frame-aware `drop_border_edges` (Vektorisierer, kein Retrain) hob ALLES ~+0.02-0.04.
>
> ---
>
> ⏩⏩⏩ **RESUME (Stand 2026-07-22 Nachmittag, ÜBERHOLT — System fertig + E2E; Historie).**
> Ältere ⏩-Blöcke darunter = nur Historie.
>
> **🆕 2026-07-22 Nachmittag: ALLE Verifikationsschritte durch — auch der letzte
> (In-Game-E2E in echter Foundry v13).** Details: notes.md OBERSTER Eintrag.
> Kurz: Modul (jetzt ID `auto-wall-companion-ml`, v2.1.0) in Forge-Welt „Wall Test"
> installiert, Wild-Crypt-Map geladen, „Detect Walls (ML)" geklickt → **116 native
> Wände in 0.49s** via HTTPS-cloudflared-Tunnel zum lokalen Student-Service, Wände
> zeichnen die Struktur sauber nach. Beweis-Screenshot:
> `vendor/auto-wall-companion/test-evidence-v13-ml-detect.png`. GOTCHA gefixt:
> Modul-ID-Kollision mit archiviertem Upstream-Paket [[foundry-module-id-collision]]
> (Foundry-„Update" zog sonst Upstream 1.2.2 ohne ML) → eindeutige ID; Fix + zuvor
> nie committete ML-Feature-Dateien im Modul-Repo committet (3eeebab). Forge-Harness:
> `scratchpad/forge/driver.py` (Playwright), Account-Session war noch gültig → kein
> Passwort nötig. **Es ist KEIN Verifikationsschritt mehr offen** — „continue" heißt
> ab jetzt nur noch Qualitäts-Kür (unten Punkt 3).
>
> **USER-AUFTRAG ERFÜLLT: End-to-End-System (Foundry-Modul + lokaler Companion-
> Service + destillierter Student) steht und ist getestet.** Volle Anleitung:
> **`DEPLOYMENT.md`**. Deadline war 23.07. Abend — fertig am 22.07. Mittag.
>
> **ERGEBNIS (in-scope-32 graph-F1): Student = 0.723 (MS) / 0.721 (single) vs
> Teacher 0.728** → Gate ≥0.72 BESTANDEN, nur 0.005 unter Teacher bei ~180x
> Kompression (1.1B DINOv2-ViT-g → 6.7M MobileNetV3-L-U-Net). single ≈ MS →
> **Deployment = single-scale 1024** (0.65s/Map hier, ~1.3s erwartet Ryzen 3600).
> **INT8 VERWORFEN** (kollabiert 0.72→0.38, MobileNetV3-Aktivierungen; fp32 ONNX
> wird ausgeliefert) [[int8-mobilenetv3-collapse]].
>
> **Artefakte (Modelle git-ignored wg. Größe, lokal vorhanden):**
> `pipeline/models/wall_student_mbv3.{pt,onnx}` (+_last.pt, +_int8.onnx),
> Pseudo-Labels `corpus/distill_pl/` (620 Maps, 797MB), Overlays
> `corpus/results/student_overlays/`, Sprint-Log `corpus/results/distill_sprint.log`.
> Pipeline: `distill_pseudolabel.py`(--fp16), `train_student.py`(--amp),
> `graph_eval_student.py`(ONNX-Pfad wenn ckpt=.onnx), `export_student_onnx.py`,
> `wall_service.py`(:8177, default single-scale), `tools/{distill_sprint,run_wall_service}.sh`.
> Modul: `vendor/auto-wall-companion` (Button „Detect Walls (ML)", module.zip 24KB).
>
> **▶️ BEI „continue" — ALLE Verifikation ist DURCH (1)+(2) unten = ERLEDIGT
> 2026-07-22 Nachmittag, NICHT wiederholen). „continue" heißt jetzt Qualitäts-Kür
> (3). Falls doch nochmal verifizieren nötig: Rezepte stehen weiter unten.**
> **(1) ✅ ERLEDIGT — Autonome Checks:** `_last.pt`=0.725 single ≈ shipped best 0.721
>   (Rauschen → ONNX unverändert). Service-E2E `pipeline/service_e2e.py` auf 3 Wild-
>   Maps grün. Belege: `corpus/results/{eval_student_last_1024,service_e2e_*}`.
> **(2) ✅ ERLEDIGT — In-Game-E2E in echter Foundry v13 (Forge):** „Detect Walls (ML)"
>   → 116 native Wände in 0.49s via HTTPS-cloudflared-Tunnel. Beweis:
>   `vendor/auto-wall-companion/test-evidence-v13-ml-detect.png`. Modul-ID-Kollision
>   gefixt → ID jetzt `auto-wall-companion-ml` v2.1.0 [[foundry-module-id-collision]].
>   Forge-Harness `scratchpad/forge/driver.py` (Playwright); Account-Session war
>   gültig → kein Passwort nötig (falls next session Login braucht: Account-SID lief
>   bis 28.07.; sonst Passwort vom User + Captcha manuell). Details: notes.md TOP.
> **(3) ▶️ AB JETZT „continue" = OPTIONALE QUALITÄTS-KÜR (kein Verifikationsschritt
>   mehr offen):** Recall-Hebel (Student R=0.688 < P=0.795) via `--tversky_beta`
>   bräuchte train_student-Erweiterung / mehr Epochen; Speed ncnn+Vulkan auf RX 6600
>   (ROCm-frei); Teacher verbessern (DINO_IMPROVEMENT_PLAN 0.728→0.9) → gratis
>   Re-Distillation via `tools/distill_sprint.sh`. **User fragen, was er priorisiert.**
>
> **GOTCHAS diese Runde:** kein zweiter Teacher daneben ladbar (contiguous-OOM
> trotz freiem Speicher); WebP>64MB braucht `OPENCV_IMGCODECS_WEBP_MAX_FILE_SIZE`
> (im Launcher gesetzt); INT8/MobileNetV3-Kollaps (Memory).
>
> **Wild-Showcases (visueller Beleg, committet):** HEAT-ep80 vs DINO-MS auf 12
> unlabeled Maps: `corpus/results/{heat,dino}_wild_showcase/collage_*.png` —
> DINO präzise aber Recall-schwach, HEAT recallt mehr + halluziniert Grids.
> Neue Tools: `pipeline/{heat,dino}_infer_showcase.py` (Inferenz ohne GT).
>
> ---
>
> **HISTORIE: HEAT-in-scope-Arc ABGESCHLOSSEN (2026-07-22 ~03:15, Plateau).**
>
> **HEAT-Ergebnis (2026-07-22): schlägt DINO NICHT.** Fine-tune konvergierte bei
> in-scope-32 graph-F1 **0.703** (ep80; Kurve ep50–80: 0.682/0.702/0.696/0.703,
> buildings ~0.69 flach, caves ~0.74 ausgeflacht; auch loss/edge_acc/corner_recall
> flach) → Training bei ep84 gestoppt (User-Regel „bei Plateau stoppen"). Beste
> Snapshots: `vendor/heat/checkpoints/ckpts_heat_fa_inscope/checkpoint_ep{60,80}.pth`.
> dd2vtt-Buildings-Stärke übertrug NICHT (HEAT-buildings 0.689 < DINO 0.721);
> caves waren HEATs bessere Hälfte (0.738). **Oracle(DINO,HEAT-ep80)=0.763** (+0.035)
> → Per-Map-Routing-Gate lohnt nicht (Schwelle ~0.85); HEATs Einzel-Wins (sewer-town
> +0.25, cave-gallery +0.21) später über Graph-Level-Edge-Merging einsammeln.
> Snapshot-Tabelle: `corpus/results/heat_snapshot_summary.txt`; Einzel-Evals
> `heat_snapshot_evals/ep*.log`. Monitor beendet sich selbst nach checkpoint_best-Eval.
>
> **BALKEN unverändert: DINO-FA-in-scope 0.728 (MS) = Champion. HEAT dd2vtt 0.926.**
>
> **▶️ NÄCHSTER SCHRITT (wartet auf User-Freigabe): `DINO_IMPROVEMENT_PLAN.md`**
> (Repo-Root, committet efccdfe) — recherchierter Phasen-Plan 0.728→0.9:
> „Recall in der Maske, Precision im Graph". Phase 0 Diagnostik (Mask-UB vs Graph-F1,
> Recall-Miss-Taxonomie) → Phase 1 Tversky-0.7 + Skeleton-Recall-Loss + Flip-TTA +
> MRF-Edge-Pruning → Phase 2 Auflösung 518 + LoRA + OHEM/FDA + gelernte Edge-
> Verification → Phase 3 DINOv3-ViT-L (GATED: User-Lizenz!) + UniMatch-V2-SSL +
> ControlNet-Synthesedaten + CAGE. User-Entscheidungen in §5 des Plans.
> Tversky-Flag-Konvention bereits VERIFIZIERT korrekt (SMP: beta→FN-Term).
>
> **EVAL-GOTCHA NEU:** `heat_eval_uvtt.py` cappt jetzt Corners auf Top-350 nach
> Confidence (vendor `all_combibations` deckt nur 2–350; spätere FT-Ckpts feuerten
> >350 auf cluttered Tiles → KeyError-Crash; gefixt + committet).
>
> **CPU-EVAL-Rezept (für HEAT-Snapshots, GPU-frei):**
> `HEAT_EVAL_DEV=cpu OMP_NUM_THREADS=8 .venv/bin/python pipeline/heat_eval_uvtt.py
> --ckpt <ckpt> --image_size 256 --fa_test --fa_list corpus/fa_test_inscope.txt
> --per_map` (~70s/Map idle, ~3min/Map unter Gemma-Contention). Overlays:
> `--overlay_dir DIR` (GRÜN=GT, ROT=pred). CPU-Fixes: DataParallel→bare+strip,
> ResNetBackbone.train()-in-place, MSDeformAttn-CPU-Fallback (vendor, git-ignored).
> In-scope-Mean IMMER selbst gegen `corpus/fa_test_inscope.txt` rechnen.
>
> Detail-Chronik: notes.md OBERSTE 3 Einträge. Commits 59bb04f → efccdfe.
>
> ---
>
> ⏩⏩⏩ **RESUME (Stand 2026-07-21 früh, ÜBERHOLT — DINO-Long; nur Historie).**
>
> **NEUE RICHTUNG (User): FA-Score auf ECHTE Wände fokussieren, Ziel >0.9 (in-scope).**
> Der alte FA-Wert ~0.55 war halb echte Maps, halb unlösbares Terrain (Sümpfe/Flüsse/
> Wüsten/Perimeter-only). Diese sind NICHT im Scope. **Höhlen BLEIBEN drin** (klare
> Fels-Kanten, funktionieren gut). Belegt per visueller GT-Overlay-Klassifikation aller
> Maps (Geometrie/Edge-Proxies trennen NICHT sauber → Entscheidung ist visuell).
>
> **SCOPE-LISTEN (committet):** `corpus/fa_test_inscope.txt` (32 Held-out = 23 buildings
> + 9 caves), `_buildings.txt`, `_caves.txt`, `_outscope.txt` (17), `_borderline.txt` (2).
> `corpus/fa_outscope.txt` = 69 Maps, die aus dem TRAINING raus sind (build_fa skippt
> sie; fa_tiles 394→275). Eval-in-scope-Mean IMMER selbst berechnen: per_map-Eval →
> Zeilen gegen fa_test_inscope.txt mitteln (kein CLI-Flag dafür).
>
> **BALKEN / ERGEBNISSE (in-scope graph-F1, n=32):**
> - Champion `wall_dino_fa.pt` (alte Daten): single **0.697**.
> - Retrain in-scope-Daten `wall_dino_fa_inscope.pt`: single **0.707** (+0.010 Data-Cleanup),
>   **multi-scale 0.728** (+0.021 MS). Mask-val-Dice war FLACH ~0.63.
> - HEAT zero-shot (sah nie FA): in-scope 0.571 / **buildings 0.614** / caves 0.459.
> - dd2vtt-Bestwert unverändert HEAT 0.926; all-domain FA-Bestwert DINO-FA 0.568(MS).
>
> **▶️ BEI „continue" ZUERST: Long-Run prüfen.** LÄUFT (setsid, überlebt /clear):
> `wall_dino_fa_inscope_long.pt` (--samples 180000=3×, bs=4, 18 val-points, KEIN Tversky
> → „länger trainieren" isoliert, wg. User-Hinweis Geduld/lokale Optima).
> Status: `grep "wall val Dice\|best Dice=" corpus/results/train_dino_fa_inscope_long.log`;
> Prozess `pgrep -f "train_dino.py.*inscope_long"`. WENN fertig: single+MS in-scope evaln
> (`graph_eval_dino.py --ckpt … --fa_test --per_map` und `graph_eval_dino_ms.py --ckpt …
> --per_map`), in-scope-32-Mean bilden, mit 0.728 vergleichen. Kurve ganz ansehen —
> NICHT bei kurzem Plateau abbrechen ([[training-patience-local-optima]]).
>
> **NÄCHSTE HEBEL Richtung 0.9 (0.728→0.9 ist groß, mehr als nur Länge nötig):**
> (1) recall-favoring Loss: `train_dino.py --tversky_beta 0.7` (Flag gebaut+verifiziert;
> P>R ist die Lücke). (2) DANN HEAT-Arc (User-Reihenfolge: erst DINO, dann HEAT):
> HEAT auf in-scope-ONLY fine-tunen (warm-start 0.926-ckpt `ckpts_heat_byol_full/
> checkpoint_best.pth`) — nie sauber gemacht (alter FA-HEAT ~0.50 war auf polluted+organic
> trainiert). HEAT ist Buildings-Spezialist; wenn Höhlen zu wenig ausdrucksstark →
> **HEAT mit MEHR Output-Vertices neu trainieren** (User-Vorgabe). Dann Per-Map-Routing
> HEAT(buildings)+DINO(caves).
>
> **GPU/RAM-GOTCHA (WICHTIG):** Parallele Session fährt **Gemma-4-31B q4_0 GGUF**
> (llama-server, ctx 96k, -ngl 99) auf DERSELBEN GPU (GB10 unified, ~128GB). Dessen
> KV-Cache frisst ~90GB → **CUDA-frei nur ~7–19GB** (obwohl OS-MemAvailable ~50GB;
> Differenz = reclaimable page-cache, das CUDA nicht gutschreibt). Daher: Training
> **bs=4**, IMMER `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`, und
> Model-Load OOMt sporadisch (contiguous-Alloc) → **Launch-Retry-Loop** nutzen. Auch
> Evals OOMen wenn Gemma spikt → retry. Page-Cache-Drop braucht root (kein sudo hier);
> nur als Pre-Load-Trick sinnvoll. Wenn User Gemma-ctx→32k senkt: bs=8 möglich (2× schneller).
> `--epochs` = nur Val-Frequenz, `--samples` = echte Trainingslänge.
>
> ---
>
> ⏩⏩ **RESUME (Stand 2026-07-20, ÜBERHOLT — Copy-Paste; nur Historie).**
> Dieser Block ist die Kurzfassung zum Weitermachen.
>
> **▶️ BEI „continue"/„mach weiter" (Stand 2026-07-20 Abend):**
> (1) diesen Block lesen, (2) `notes.md` OBERSTEN Eintrag („Copy-Paste") lesen,
> (3) prüfen ob das COPY-PASTE-Training fertig ist:
> `grep "best Dice=\|wall val Dice" corpus/results/train_dino_fa_cp.log`
> (Prozess: `pgrep -f "wall_dino_fa_cp"`; Modell `pipeline/models/wall_dino_fa_cp.pt`;
> läuft via setsid, überlebt /clear; der Notify-Waiter aus der Vorsession ist tot →
> Status per Log/Prozess selbst prüfen).
> (4a) WENN fertig: auf FA held-out UND dd2vtt-6-hart evaluieren, vergleichen mit
> Baseline **FA 0.567 (single) / 0.568 (multi-scale), dd2vtt 0.894**:
> `.venv/bin/python pipeline/graph_eval_dino.py --ckpt pipeline/models/wall_dino_fa_cp.pt --tag CP --fa_test --per_map`
> (FA) und ohne `--fa_test` (dd2vtt). Für Multi-Scale: `graph_eval_dino_ms.py`.
> Ergebnis in notes.md + committen. Wenn Copy-Paste hilft → als nächstes
> Style-Randomization / Skeleton-Recall-Loss (siehe notes „Copy-Paste"-Eintrag,
> Research-Shortlist). Wenn nicht → dem User berichten.
> (4b) GPU ist 1 Karte, seriell. Lange Jobs IMMER mit
> `setsid bash -c 'export …; /abs/pfad/.venv/bin/python -u …'` starten (überlebt
> /clear; venv-PATH absolut, sonst `python: command not found`).
>
> **STAND (was erledigt ist): Der 5-Schritt-MoE-Plan ist DURCH, mit klarem Ergebnis:**
> #1 2×-Seg → FA-Graph 0.505 (kein Gewinn; build_graph ist Flaschenhals).
> #2 DINO zero-shot FA 0.321. #3 **DINO-FA-Experte fine-getunt → FA 0.553/0.568(MS),
> dd2vtt 0.894** (bestes FA-Modell, `wall_dino_fa.pt`; Bugfix: FA-val-Split statt
> donjon-val). #4 Multi-Scale-Inferenz +0.015 (ASPP zurückgestellt, low-ROI).
> #5 **MoE-Gate VERWORFEN** — Oracle-Decke nur +0.047(dd2vtt)/+0.007(FA) über
> DINO-FA-allein → Gate lohnt nicht (wie „Fusion widerlegt" zuvor). NEUE RICHTUNG
> (User): **Copy-Paste-Augmentation** (non-wall-Clutter einpasten, Wandmaske gleich)
> gegen FA-Fehler — LÄUFT gerade (`wall_dino_fa_cp.pt`).
>
> **AKTUELLER BESTWERT FA: DINO-FA `wall_dino_fa.pt` = 0.568 (multi-scale
> {768,1024,1536}) / 0.553 (single), dd2vtt 0.894.** dd2vtt-Bestwert bleibt HEAT
> 0.926. HEAT+DINO NICHT fusionieren (Oracle-Decke zu niedrig, belegt).
>
> **⬇️ HISTORIE / ÜBERHOLT (der MoE-Plan unten wurde ABGEARBEITET; Ergebnis siehe
> STAND oben — Gate verworfen, DINO-FA ist der Gewinner). Nur noch Kontext:**
>
> **🔴 (ÜBERHOLT) FOKUS war: GELERNTES MoE(HEAT,DINO) + MULTI-SCALE über ALLE
> Domänen.** Kurzfassung des damaligen Plans:
> - **build_graph-Hang GEFIXT** (`graph_infer.py`, committet 5475253): O(V²)/O(E²)
>   → Raum-Hash-Snap + Worklist-Merge; warehouse@2048 >110s→0.7s, Output identisch.
>   `--fast` nicht mehr nötig; echter piecewise-linear-Output läuft voll-auflösend.
> - **Saubere FA-Baselines** (51-Map-Held-out, nach Re-Harvest+Tile-Rebuild):
>   HEAT/BYOL zero-shot 0.409 (excl-deg 0.432); **Seg-U-Net `wall_graph_fa_clean.pt`
>   echter Graph-Output 0.507 (excl-deg 0.536)**, Masken-UB 0.559. **Seg > HEAT auf FA.**
> - **FUSION-THESE WIDERLEGT:** Per-Map-Oracle max(HEAT,Seg) nur +0.017 über Seg.
>   HEAT↔DINO-Komplementarität ist eine dd2vtt-Sache, nicht FA.
> - **USER-AUFTRAG:** MoE(HEAT,DINO) mit **gelerntem Gate**, beide fine-tunen,
>   **donjon (170k) bleibt in JEDEM Training**, Architektur **aufbohren + Multi-Scale**
>   (DINO-Engpass SZ=252). ALLE Domänen abdecken. Gate PRO PIXEL auf vollem Pool →
>   `[Bild,prob_HEAT,prob_DINO]`→Fusion→build_graph→**piecewise-linear (H4)**.
> - **LÄUFT (nohup, überlebt /clear):** 2×-Seg `wall_graph_fa_clean2x.pt`
>   (samples 240k/12ep, Log `corpus/results/train_seg_fa_clean2x.log`) — prüft ob
>   mehr Training hilft. Bei /clear-Resume: Log/mtime prüfen, ob fertig, dann messen
>   (`WALL_GRAPH_CKPT=…clean2x.pt python pipeline/graph_eval_uvtt.py --fa_test --per_map`).
> - **Task-Liste #1–#5** = die 5 Schritte (2x-Seg messen → DINO zero-shot FA →
>   DINO-Fine-Tune inkl FA → Multi-Scale-Decoder → Gate). Reihenfolge/Details in
>   notes.md-Eintrag „(Plan)". `train_dino.py` gepatcht (`--real` komma-getrennt,
>   NICHT committet — erst nach erstem DINO-Lauf verifizieren+committen).
> - **Output MUSS piecewise-linear bleiben; Segmentierung nur intern.**
>
> **Nach `/clear` in dieser Reihenfolge lesen:**
> 1. **Diesen RESUME-Block** (bis „GOTCHAS" unten) — Gesamtstand in Kurzform.
> 2. **`notes.md`**, oberste ~15 Einträge (neueste oben) — chronologischer
>    Detailverlauf mit Metriken/Begründungen.
> 3. **Auto-Memory** (`…/memory/MEMORY.md` + Einträge) — wird automatisch als
>    system-reminder geladen; enthält u.a. den DINO+HEAT-Ensemble-Vorschlag und
>    die Forgotten-Adventures-Notiz. NICHT als Live-Zustand behandeln (verifizieren).
> 4. Bei Bedarf, themenspezifisch: `OBJECT_MODELS.md` (Objekterkennung),
>    `ML_TRAINING_DATA.md` (Datenquellen), `corpus/real_uvtt/README.md`
>    (geharvestete Maps + Lizenzen).
>
> ### Wo wir stehen (das Projekt hat sich stark entwickelt)
> Ursprung: Add-on für Foundry VTT, das Wände auf Battlemaps automatisch zeichnet.
> Der Auto-Wall-Companion-Modul-Teil ist FERTIG & in Foundry v13 live verifiziert
> (`vendor/auto-wall-companion`, Beweise `corpus/results/test-evidence-v13-*`).
> Der Fokus liegt jetzt auf einer **eigenen ML-Wanderkennung** (Segmentierung →
> planarer Graph), weil klassisch CV/Auto-Wall auf harten Maps unbrauchbar war
> (F1 ~0.2–0.4).
>
> ### Aktueller BESTWERT (harte, ausgehaltene dd2vtt-Maps, echte GT)
> **HEAT/BYOL fine-tuned + Bildrand-Filter: F1 0.926 / P 0.89 / R 0.97.**
> Checkpoint: `vendor/heat/checkpoints/ckpts_heat_byol_full/checkpoint_best.pth`,
> Eval: `pipeline/heat_eval_uvtt.py --image_size 256`. Backbone per BYOL-SSL auf
> Domäne vortrainiert (`train_byol.py` auf 176k-Pool → `inject_byol_heat.py` →
> HEAT-Finetune). Vorheriges HEAT (ImageNet-Init) 0.908; BYOL-SSL brachte +0.018.
> Verlauf: CV 0.22 → SAM 0.39 → donjon 0.43 → Mix+clDice 0.73 → ResNet-Graph
> 0.74 → DINO-Graph 0.834 → +Randfilter 0.896 → HEAT-ft 0.908 → **HEAT/BYOL
> 0.926**. Zweitbestes (komplementär): DINO-Graph 0.896 (`wall_dino_vitg.pt`).
> DINO+JEPA-SSL SCHEITERTE (0.36, Collapse; JEPA-Rezept fragil auf kleiner
> Domäne — BYOL robust). Nächster Hebel: DINO+HEAT-Ensemble (Oracle-per-map
> ~0.94). Produkt-Plus HEAT: 49M Params, nativ wenige gerade Segmente (H4).
>
> ### Was GERADE läuft (Stand 2026-07-20 Nachmittag)
> **2×-Seg-Training** (nohup PID kann tot sein nach /clear, aber Prozess läuft
> weiter; Log `corpus/results/train_seg_fa_clean2x.log`, Modell
> `pipeline/models/wall_graph_fa_clean2x.pt`). RESUME: prüfen ob „best wall Dice"
> im Log steht (=fertig); wenn ja, Task #1 (messen) und weiter mit #2–#5.
> Die frühere SSL→Finetune-Kette ist durch: HEAT/BYOL 0.926 (dd2vtt-Bestwert),
> DINO/JEPA gescheitert (0.36, Collapse). GPU: 1 Karte, Jobs SERIELL fahren.
> GOTCHA aus dieser Runde (notes 2026-07-17): Orchestrator-Warteschleifen NIE auf
> `pgrep -f "train_X.py"` — matcht eigene Beobachter-Kommandos (Selbstmatch), hing
> ~20h. Auf Artefakt/Logzeile warten, nicht auf Prozessnamen.
>
> ### Nächste Schritte (Reihenfolge + WARUM) — Vorschläge, User entscheidet
> 1. **DINO+HEAT-Ensemble**: HEAT 0.926 und DINO-Graph 0.896 sind per-Map
>    komplementär (Oracle-per-map ~0.94). Kanten mergen + gegenseitige
>    Verifikation über die jeweils andere Wandwahrscheinlichkeit. Klarster Hebel.
> 2. **Foundry-E2E-Test** des 0.926-HEAT/BYOL-Modells im Test-World „wall-test":
>    Wände aus dem HEAT-Output → UVTT → Import → in-game prüfen (H2).
> 3. **JEPA reparieren** (NIEDRIGER ROI): Collapse-Schutz (VICReg-Varianz/
>    Kovarianz-Reg), nur last-1/2 Blöcke, EMA-mom→0.999+. Nur wenn DINO-Zweig
>    weiterverfolgt wird — HEAT/BYOL ist ohnehin besser.
> VERWORFEN (empirisch widerlegt, NICHT erneut versuchen): Grounding DINO
> zero-shot für bridge/chimney-Korrektur (zu verrauscht, notes 2026-07-15);
> mehr donjon-Daten allein (Domänenkluft); reines JEPA-SSL auf kleiner Domäne.
>
> ### WARUM dieser Weg
> - **Domänen-Mix** (reale dd2vtt-Maps + donjon) war DER Durchbruch (0.43→0.73).
>   Mehr donjon allein bringt nichts (Domänenkluft Pixelart↔gemalt); der Real-
>   Anteil ist der Hebel. Reale Labels: 62 dd2vtt-Maps (`vendor/vtt-maps`, Bild+
>   Wände) + donjon-Synthetik (gleicher Seed, Standard-Stil → Wandmaske, hübscher
>   Stil → Trainingsbild) + Reddit-Pseudolabels (wo CV & SAM übereinstimmen).
> - **clDice** = Verbundenheits-Loss (lange, unverbundene→bestraft). **Footprint-
>   Labels** = gelernte, variable Wanddicke (kein fester Postprocessing-Merge).
>   **Planarer Graph** (Junction-Kanal + Skelett+DP + Kollinear-Merge) = Punkte +
>   Kanten + Dicke pro Abschnitt + Knoten-Reduktions-Reg (User-Wunsch).
> - **DINO-Fine-Tune** = stärkere vortrainierte Features testen (nur letzte 4 Layer).
>
> ### Pipeline-Dateien (`pipeline/`)
> `grid_detect.py` Raster · `grid_walls.py` CV-Grid-Detektion (+ Helfer: merge_runs,
> weld_endpoints, prune_isolated) · `sam_walls.py` SAM-Regionen→Wände ·
> `region_classifier.py`/`train_region_clf.py` (verworfen) · `uvtt.py` dd2vtt-Parser ·
> `donjon_harvest2.py` donjon-Harvester · `train_seg.py` U-Net-Training (clDice,
> grid-aug, last-8) · `train_graph.py` 2-Kanal Wand+Junction · `graph_infer.py`
> Graph-Aufbau · `graph_eval_uvtt.py`/`seg_eval_uvtt.py` Eval · `vectorize_walls.py`
> Polylinien · `build_real_tiles.py` reale+Pseudo-Kacheln · `train_dino.py` DINO
> (`--backbone_init` lädt JEPA-Backbone) · `graph_eval_dino.py` DINO-Graph-Eval
> (`--ckpt`/`--tag`) · `dino_features.py` DINO-Feature-Probe · `infer_seg.py`
> Inferenz. **SSL+HEAT (neu):** `dd2vtt_to_heat.py` dd2vtt→S3D-Konverter ·
> `heat_eval_uvtt.py` HEAT-Eval (nutzt `drop_border_edges`) · `train_jepa.py`
> I-JEPA-SSL für ViT-g (GESCHEITERT, Collapse) · `train_byol.py` BYOL-SSL für
> resnet50 (ERFOLG) · `inject_byol_heat.py` BYOL-Gewichte→HEAT-Init ·
> `jepa_split.py` Drakkenheim-Split. HEAT selbst: `vendor/heat` (woodfrog/heat).
>
> ### GOTCHAS (haben Zeit gekostet)
> - **pgrep/pkill Selbst-Match:** NIE `pkill -f "train_X.py"` in einem Befehl, dessen
>   eigene Zeile „train_X.py" enthält → killt den eigenen Wrapper (Exit 144) bzw.
>   Endlosschleife. Bracket-Trick `[t]rain_X` oder per PID killen.
> - **Gated (401):** DINOv3, Forgotten-Adventures-Assets → brauchen User-Token.
>   Zugänglich: DINOv2 (torch.hub), donjon, mbround18/vtt-maps.
> - **Env:** `.venv` (torch 2.13+cu130, ultralytics, segmentation-models-pytorch,
>   skimage, scikit-learn). GB10 aarch64 CUDA 13.0. Node: `~/.nvm/versions/node/v24.18.0/bin`.
>   numpy 2.0: `np.ptp(a,axis=)` statt `a.ptp()`.
> - **Forge:** Instanz auf v13, Test-Welt „wall-test" existiert; Passwort im Chat
>   geteilt → User soll rotieren.
> - **Lange Jobs:** `run_in_background:true`; Fortschritt über Modell-Dateidatum +
>   Log-`grep` prüfen (Task-tmp-Pfade sind session-spezifisch, Modelle/corpus/notes
>   sind dauerhaft).

---

This file is a step-by-step operating manual, not background reading. Follow it
literally. When it says "do X, do not ask", do X without asking. When it says
"measure", a glance at a screenshot does not count.

## Project goal

Build a **Foundry VTT add-on module** that takes a scene's battle-map image and
**automatically draws the walls** (plus doors and, later, windows/lights) as
native Wall documents, so a GM can import a map and have working vision/movement
blocking in seconds instead of tracing hundreds of segments by hand.

Verified context (2026-07-14; re-verify before relying on it):
- Foundry VTT stable is **v14** (release 14.359); v13 is still widely used.
  Target v13+v14 compatibility unless decided otherwise.
  https://foundryvtt.com/releases/
- **Prior art exists and must be studied, not reinvented:**
  [Auto-Wall](https://github.com/ThreeHats/auto-wall) — external PyQt6 desktop
  app, OpenCV edge/color detection, exports **UVTT** (Universal VTT JSON);
  its companion module: https://foundryvtt.com/packages/auto-wall-companion.
  UVTT files are imported into Foundry via "Universal Battlemap Importer".
  Our differentiator: detection **inside Foundry** (or one-click from Foundry),
  no external app round-trip.
- Official API docs: https://foundryvtt.com/api/ — the ONLY authority on the
  Foundry API (see hard rule H1).

## PRIME DIRECTIVE (user, 2026-07-14): buy before build

If Auto-Wall + Universal Battlemap Importer already do what the user wants,
USE THEM — implement nothing. Therefore:

- **Phase 0 (mandatory, before any implementation):** evaluate the existing
  toolchain end-to-end — install Auto-Wall locally (MIT license, Linux
  .deb/AppImage), run it on a small representative map set, export UVTT,
  import into the user's Forge instance via Universal Battlemap Importer,
  and judge the resulting walls in-game (H2: overlays/screenshots + numbers).
- **Decision gate:** report findings as fit/gap table. Only gaps the user
  confirms as blocking justify building anything, and then the smallest
  thing that closes the gap (e.g. a thin Foundry module wrapping Auto-Wall's
  pipeline for one-click use) — not a from-scratch rewrite.
- Everything below about building a module is CONDITIONAL on that gate.

## Open decisions (settle with the user before building the affected part)

0. **Phase-0 verdict** — does Auto-Wall meet the need as-is? (Known caveat to
   probe: it is an interactive desktop app with an export/import round-trip,
   not one-click inside Foundry; is that acceptable to the user?)
1. **Architecture (only if building)** — where does the computer vision run?
   (a) fully in-browser (JS: OpenCV.js / onnxruntime-web) — zero install, but
       heavy assets and limited CPU;
   (b) companion Python service the module calls (localhost HTTP) — full
       OpenCV/ML power, but extra install step;
   (c) hybrid: classical CV in-browser, optional ML service for hard maps.
   Prototype the detection pipeline in Python FIRST regardless (fast iteration,
   see `skills/wall-detection-pipeline.md`); port or wrap once quality is proven.
2. **Distribution** — GitHub repo + Foundry package listing (public) vs. private.
   Publishing anywhere is ask-first.

## Working rules

**Autonomy.** For multi-step technical tasks (pipeline experiments, module
builds, iterative debugging) do NOT stop after each sub-step to ask for
confirmation. Work the whole task through to done or to a hard-to-reverse
action. Give one-line progress notes on the way. "Go" / "yes" authorizes the
WHOLE task loop below, not just the next sub-step.

**Never ask permission to:** edit files, run builds/lints/tests, run the
detection pipeline on test maps, render/inspect overlays, create scratch files,
manage own background processes, initialize/commit to the LOCAL git repo,
update `notes.md`/`MEMORY.md`, fix bugs discovered during verification (fix,
verify, mention in the report).

**Ask first, always:** publishing anything (GitHub push to a public remote,
Foundry package registry, forum posts); deleting files you did not create;
anything that modifies a real Foundry user-data world outside the dedicated
test world; expanding scope beyond the request (propose it in the report
instead).

**Research.** Research every factual claim (API signatures, format specs,
version compatibility), cite the URL, and re-fetch the URL to confirm it
supports the claim before writing it down. This applies doubly to the Foundry
API: it changes between major versions and training-data memory of it is
unreliable (H1).

**Hypotheses.** Treat every detection idea ("Canny + Hough will find these
walls", "color clustering separates floor from wall") as a hypothesis to
refute: run it on a realistic, diverse map corpus and actively hunt for
counterexample maps that break it. One counterexample kills the general claim —
then check whether it still holds for a well-defined special case (e.g. "maps
with uniform dark wall strokes") and hunt counterexamples for THAT. When the
user proposes a hypothesis, your first move is also to look for
counterexamples. Record verdicts in `notes.md`.

## THE TASK LOOP — follow for EVERY change, in order, without stopping

1. **Baseline.** Before changing detection code, save the current corpus
   metrics and overlays: `tools/benchmark.sh --tag baseline` (once it exists;
   until then, copy current outputs to `/tmp/baseline_drawmaps/`).
2. **Edit.** Smallest change that fixes the problem — at the right LEVEL: a
   detection failure on one map is a pipeline/parameter bug; fix the pipeline,
   never hand-tune a single map (H6).
3. **Build & lint.** Python: run the pipeline entry point + `ruff check`.
   Module JS: the build/lint command in `module/README.md`. Never treat a run
   with errors as success.
4. **Regression check.** Re-run the corpus benchmark and diff metrics against
   baseline. Maps you did NOT intend to affect must not regress; maps you DID
   target must improve. If nothing changed, your edit was a silent no-op — find
   out why before going on (H8).
5. **Inspect.** Render wall overlays for every changed map and actually LOOK
   at them with the Read tool (H2). For module changes: load the test world,
   run the feature, screenshot, look.
6. **Record.** Add an entry at the TOP of `notes.md`: what was wrong, root
   cause, fix, metric deltas, verification scope. Reusable pitfalls go into the
   matching skill file. Commit locally with a message describing cause and fix.
7. **Report.** Outcome first, then detail (see Reporting).

## HARD RULES

- **H1 — Never trust API memory.** Before using any Foundry API (document
  schema, hook name, canvas API, manifest field), verify it against
  https://foundryvtt.com/api/ (or the foundryvtt.wiki dev guides) for the
  TARGETED core version, and record the verified fact with URL in
  `skills/foundry-module-dev.md`. A module that "looks right" from memory and
  fails on load is the expected failure mode, not bad luck.
- **H2 — Measure, don't eyeball.** Wall quality is judged by (a) overlay
  renders you actually looked at AND (b) numbers: segment count, total length,
  coverage/precision vs. hand-made ground-truth walls on the test corpus
  (`skills/verification-and-benchmarking.md`). "Looks plausible" is not a
  result.
- **H3 — Corpus, not anecdotes.** Never judge a detection change on one map.
  The test corpus spans styles (hand-drawn, Dungeondraft, photorealistic,
  gridded/gridless, dark/light). A change ships only if the corpus says net
  improvement and no targeted map regressed.
- **H4 — Walls must be editable, not pixel noise.** Output few, long, snapped
  segments a GM can adjust (simplification/merging is part of the pipeline,
  not optional polish). A wall set with thousands of 2-px segments is a
  failure even if coverage is 100% — it lags the canvas and can't be edited.
- **H5 — Never destroy user data.** The module never deletes or overwrites
  existing walls without an explicit in-UI confirmation, and every bulk
  operation must be undoable (single undo step / stored previous state).
  Development happens in a dedicated throwaway test world only.
- **H6 — Fix systemically.** A bug visible on one map/scene is a bug in the
  algorithm or its parameters. Fix it there, then re-verify the WHOLE corpus,
  not just the reported map. Per-map overrides only for genuinely map-specific
  values, and they live in explicit config, not code.
- **H7 — Coordinates are a minefield.** Image pixels ≠ canvas coordinates:
  scene padding, background offset/scale, and grid size all shift wall
  endpoints. Every coordinate transform gets a unit test with known-answer
  fixtures before it is used (`skills/foundry-module-dev.md` §coordinates).
- **H8 — Verify the EFFECT, not the absence of errors.** A change that runs
  cleanly can be a complete no-op. Prove the new logic fires: log the computed
  value once, or check that exactly the intended corpus maps changed.

## Environment

- Python venv: `/home/spark1admin/draw_maps/.venv` — create with
  `python3 -m venv .venv` at first need; system Python is PEP-668
  externally-managed, never pip-install into it.
- Long runs (corpus benchmarks, model inference) go into tmux, not the Claude
  session: `tmux new -s drawmaps`, log via `tee /tmp/drawmaps_run.log`.
- GPU: CUDA available (`cuda`) if ML models are used.
- Local git: initialize at project start (pre-authorized). Remote publishing:
  ask first.
- Foundry test instance: document install path, launch command, and test-world
  name in `notes.md` as soon as it exists; never point the module at a real
  world.

## FILE MAP (planned layout — keep current as the project grows)

| Path | Role |
|---|---|
| `CLAUDE.md` | this operating manual |
| `skills/` | runbooks; `skills/README.md` is the menu — scan it first |
| `pipeline/` | Python detection prototype (the algorithm source of truth) |
| `module/` | the Foundry module (module.json, esmodules, styles, lang) |
| `corpus/` | test maps + ground-truth walls (`corpus/README.md` lists provenance/licenses) |
| `tools/` | benchmark.sh, overlay renderer, metrics, UVTT export/import helpers |
| `notes.md` | session log, newest on top — read the top 2–3 entries when starting work |
| `MEMORY.md` | intermediate state snapshots at every major step (dpscans convention) |

## Reporting

Lead with the outcome ("wall detection on the corpus: precision X→Y, overlays
verified on maps A–C, committed as <hash>"), then root cause, then verification
scope, then anything you noticed but did not do (as proposals, not questions).
Report failures just as plainly: if a step failed or was skipped, say so —
never present unverified work as done.

# Delegate isolated tasks to subagents with a lean context to save tokens

If you can split up your task into a series of isolated subtasks with some potential stitching together of the master agent where the stitching task is significantly easier than the overall task and where each subtask can be described with a fraction of the master agents' context, please spawn subagents for these isolated subtasks, give them the part of your context that they need for that task (try to keep their context as lean as possible for that subtask) and ask them to provide a report that includes all challenges that were encountered on the way and a description of the result. The master agent should then store the full report and only remember a summary that contains a pointer to all the challenges and a pointer to key points of the result such that the master agent knows where to look if more detailed information is needed.
