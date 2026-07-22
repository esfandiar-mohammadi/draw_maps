# Distillation-Plan: DINO-Pipeline → User-Hardware (RX 6600 / Ryzen 3600)

Status: **VORSCHLÄGE, noch nicht ausgeführt** (User wählt). Stand 2026-07-22.
Basis: 4 Web-Research-Agents (Conv-Split-Trees / CNN-Student+KD+Deployment /
exotische CPU-Studenten / AMD-GPU-Verifikation) + lokale Messungen. URLs inline.

## 0. Ziel & Constraints

- **Qualitätsziel (User): „ähnliche Performance wie die DINO-Pipeline"** — aktuell
  in-scope graph-F1 **0.728** (MS). Jede Teacher-Verbesserung aus
  `DINO_IMPROVEMENT_PLAN.md` überträgt sich später per Re-Distillation gratis.
- **Ziel-Hardware (User, 20% Reserve freihalten)**: AMD Ryzen 5 3600 (6C/12T →
  Budget ~9–10 Threads), **Radeon RX 6600 8GB (Navi 23, gfx1032, RDNA2)** →
  Budget ~6,4 GB VRAM, 16 GB RAM → Budget ~12 GB. Arch Linux (Rolling!).
- Latenz: wenige Sekunden pro Map ok (One-Shot-Import-Flow).
- Produktkontext: Foundry-Modul → idealerweise Browser (WASM/WebGPU), sonst
  lokaler Companion-Service.

## 1. Das Paper, das der User meinte — IDENTIFIZIERT

**Laptev & Buhmann, „Convolutional Decision Trees for Feature Learning and
Segmentation", GCPR 2014** (Best Paper Award). Multivariater Entscheidungsbaum,
dessen Split-Funktion pro Knoten ein **gelernter Convolution-Kernel** ist
(Gradientenabstieg pro Knoten, Baum wird simultan gewachsen); Task: binäre
Segmentierung (EM-Membranen). https://doi.org/10.1007/978-3-319-11752-2_8

Ehrliche Einordnung als Distillations-Ziel:
- **Kein offizieller Code** (nur Dritt-Reimplementierungen, z. B. 2024
  Blood-Cell-Variante).
- **Keine publizierte Distillation eines großen Vision-Modells in Conv-Split-Trees**,
  keine Evidenz für 1024²-Segmentierung auf CPU vs. kleine CNNs → Forschungs-Bet.
- Verwandte Familie: Frosst&Hinton Soft-Tree-Distillation (MNIST-Skala,
  arXiv:1711.09784), Deep Neural Decision Forests (ICCV'15, behält CNN-Backbone),
  Adaptive Neural Trees (ICML'19), TAO-oblique-Trees (schnellste echte Bäume,
  aber lineare Splits). **Der CPU-erprobte Baum-Präzedenzfall für UNSER Problem
  ist Structured Edge Forests** (Dollár&Zitnick ICCV'13: RF sagt strukturierte
  16×16-Edge-Patches vorher, 30 FPS single-thread, Code https://github.com/pdollar/edges,
  auch in OpenCV ximgproc) — Wände ≈ Kanten.

## 2. Harte Fakten aus der Recherche (entscheidungsrelevant)

**AMD-GPU (RX 6600) — Teacher-direkt ist FRAGIL:**
- gfx1032 in **keinem** aktuellen ROCm offiziell (nur PRO W6800 als RDNA2);
  `HSA_OVERRIDE_GFX_VERSION=10.3.0` funktionierte historisch, ist aber **ab ROCm
  6.4.3+ kaputt (SIGSEGV)** → Pin auf 6.4.1 nötig — auf Arch (rolling) ein
  Dauer-Hazard (https://github.com/ollama/ollama/issues/12111).
- ONNX Runtime: ROCm-EP **entfernt** (≥1.23), MIGraphX-EP nimmt die Karte nicht,
  Vulkan-EP existiert nicht.
- 8 GB VRAM: ViT-g (2,2 GB fp16 + Aktivierungen, MS-Tiling) grenzwertig.
- **ROCm-freie GPU-Pfade für kleine CNNs**: (a) **ncnn+Vulkan** über Mesa/RADV —
  U-Net-erprobt, ONNX→ncnn-Konverter; (b) **WebGPU im Browser** (ort-web /
  transformers.js v3; Chrome auf Linux am sichersten, Firefox-Linux WIP).

**Student-Kandidaten (lokal GEMESSEN, ONNX-Export verifiziert; onnx+onnxruntime
sind jetzt im .venv):**
- smp-U-Net **MobileNetV3-L** (6,7M): **0.18 s @512² / 0.63 s @1024²** nativ CPU.
- smp-U-Net **EfficientNet-lite0** (5,2M): 0.23/0.67 s. Konservativste Ops → bester INT8-Pfad.
- Referenz: unser ResNet34-U-Net (24,4M): 1,5 s @1024² CPU fp32 (dieser Host).
- Fallback-Architektur: **PIDNet-S** (7,6M, 78.6 Cityscapes = beste ≤10M-Klasse;
  Boundary-Branch passt konzeptionell zu Wall+Junction).

**KD-Rezept (präzedenzbelegt):**
- **Output-Space-Distillation mit Teacher-Pseudo-Labels auf UNLABELED Daten** ist
  der stärkste belegte Hebel: **Depth Anything V2** trainierte Studenten NUR auf
  62M DINOv2-G-Pseudo-Labels, fand sie BESSER als manuelle Labels
  (https://arxiv.org/abs/2406.09414). MobileSAM: 632M→5,8M (~110×) „near-parity",
  <1 GPU-Tag (https://arxiv.org/html/2306.14289). DINOv2/v3 destillieren selbst
  (v3 sogar ViT→ConvNeXt — Metas eigener ViT→CNN-Präzedenzfall).
- Für uns: Teacher-Soft-Maps (wall-prob + junction) auf **176k unlabeled Crops**
  regressieren (BCE/MSE, keine Temperatur nötig) + **275 echte Maps als hart
  gewichteter Anker** (α≈0.3–0.5) + bestehender clDice/Aug-Stack.
- Feature-KD nur bei Plateau: **CWD** (channel-wise, arXiv:2011.13256) — Methoden
  clustern eng (+1–3 mIoU; CIRKD <1 über CWD, lohnt nicht).
- **Retention ehrlich**: 5–10× Kompression = 95–98% Teacher-Qualität; unsere
  ~200× (1.1B→6M) hat nur qualitative Präzedenz → **einige Punkte graph-F1
  Verlust einplanen**; binäre Ein-Domänen-Tasks sind das gutmütigste Regime
  (MK-UNet 0.32M ≥ TransUNet 105M auf 6 binären Medizin-Tasks).

**Deployment-Realität:**
- **Foundry setzt keine COOP/COEP-Header → kein WASM-Threading** (empirisch
  verifiziert). Single-Thread-WASM+SIMD = Floor: ~2–8 s pro 512²-Tile für 5–7M-
  Studenten (±2×, extrapoliert von IMG.LY-44M-Benchmark). **INT8 bringt in WASM
  KEINEN Compute-Speedup** (kein int8-dot-product in fixed-width WASM-SIMD,
  ORT#22533) — nur 4× kleinerer Download.
- Nativ: INT8 (static QDQ, **per-channel**! per-tensor kollabiert: 72.9→41.4 vs
  71.4 mIoU) = ~2–4× auf x86; Ryzen 3600 hat kein VNNI → eher 1,7–2,2×.
- **Kein existierendes Foundry-Modul führt ein lokales ML-Modell im Browser aus —
  wir wären die Ersten.**

**Exotische Optionen (geprüft):**
- **LUT-Netze** (SR-LUT/MuLUT/HKLUT): 149 ms CPU/~100 KB, pur WASM-fähig, aber
  Rezeptivfeld ~9×9 → als Gesamtmodell für Wand-vs-Möbel fast sicher zu klein;
  allenfalls Refinement-Kopf.
- **Low-Res-Student + Fast Guided Filter** (OpenCV ximgproc, >10× Speedup) oder
  Fast Bilateral Solver (0,85 s/MP): CPU-erprobter Multiplikator; Risiko: dünne
  Wände/Junction-Peaks — Junction-Kanal ggf. auf Student-Auflösung lassen.
- **Konfidenz-Kaskade** (Deep Layer Cascade: nur ~13% der Pixel brauchen die
  tiefe Stufe, mIoU sogar +): passt perfekt (Maps sind großteils leerer Boden).
- Verworfen: AdderNet/Binary-Nets (kein CPU/WASM-Pfad), Sparse-Conv-Libs
  (falsches Werkzeug), Weightless-NNs (FPGA-Klassifikation).

## 3. VORSCHLÄGE (ranked)

### P1 — DEFAULT: CNN-Student-Distillation (Empfehlung)
5–7M-U-Net (MobileNetV3-L oder EffNet-lite0; PIDNet-S als Alternative bei
Plateau), 2-Kanal-Head. KD: Teacher-Pseudo-Labels auf 176k Crops + 275-Map-Anker
+ clDice-Stack; CWD nur bei Plateau. Deployment zweistufig:
- **Nativ** (Companion/Electron): ncnn+Vulkan auf der RX 6600 (ROCm-frei,
  sub-Sekunde) und/oder ONNX-CPU INT8 (~1–2 s/Map auf Ryzen 3600 mit 9 Threads).
- **Browser** (Modul, zero-install): ort-web Single-Thread-WASM+SIMD, 512²-Tiles
  mit Overlap-Blending im Web Worker (~zig Sekunden/Map, für Import-Flow ok);
  WebGPU als opportunistischer Fast-Path (Chrome).
**Aufwand: ~4–6 Tage bis messbarem Go/No-Go** (Pseudo-Labeling ~1 GPU-Tag auf
GB10 + Student-Training 1–2 Tage + Export/INT8/Benchmark 1 Tag + ort-web-Proto
1–2 Tage). Risiko: Qualitäts-Gap bei 200× — Messlatte: in-scope-32 graph-F1
(gleiches Protokoll, build_graph bleibt identisch).

### P2 — User-Idee, seriös verprobt: Baum-Distillation (1–2-Tage-Probe)
**Structured-Forest/GBT-Variante** (Dollár-Stil: strukturierte Output-Patches;
Training auf Teacher-Soft-Labels; Inferenz kompiliert via lleaves/treelite —
10–30× über Stock-LightGBM): CPU-Präzedenz 30 FPS auf Kanten, trivial WASM-fähig
(pures Branching, keine NN-Runtime). **Unpubliziert für Deep→GBT-Dense-Distillation**
→ als zeitboxierte Probe fahren, Qualitäts-Ceiling auf gemalten Texturen ist DIE
offene Frage. Conv-Split-Trees (Laptev) selbst: nur wenn Interpretierbarkeit ein
Eigenziel wird — Reimplementierung nötig, ungewisses Payoff.

### P3 — Multiplikator für P1 (einbauen, wenn P1 steht)
Student bei 256–384px rechnen + **Fast Guided Filter** auf 1024 (Wall-Kanal;
Junction-Kanal nativ) + **Konfidenz-Kaskade** (nur unsichere Bänder in den
Student). Jedes Teil OpenCV-fertig; zusammen ~5–10× Budget-Gewinn → macht sogar
den Browser-Pfad bequem. Optional später LUT-Refinement-Kopf.

### P0 — NICHT empfohlen als Produktpfad: Teacher direkt auf RX 6600
Nur als Power-User-Notlösung dokumentiert: PyTorch-ROCm mit
HSA_OVERRIDE=10.3.0 **und ROCm-Pin auf 6.4.1** (kämpft mit Arch-Rolling), 8 GB
grenzwertig, ORT-GPU-Story tot. Fragil; Distillation ist der robuste Weg.

## 4. Empfohlene Reihenfolge

1. **P1 bauen** (Pipeline ist Teacher-agnostisch — jetzt mit 0.728-Teacher bauen,
   später gratis vom verbesserten Teacher re-destillieren).
2. Parallel/danach **P2-Probe** (1–2 Tage, beantwortet die User-Frage empirisch).
3. **P3 einbauen**, sobald P1-Qualität steht.
4. Teacher-Verbesserungen (DINO_IMPROVEMENT_PLAN) laufen unabhängig weiter;
   nach jedem Teacher-Sprung: Re-Pseudo-Labeling + Student-Refresh (~1–2 Tage).

## 5. Offene User-Entscheidungen

1. Welcher Vorschlag zuerst (Empfehlung: P1, P2 als Probe parallel)?
2. Deployment-Priorität: Browser-Modul (zero-install, langsamer) vs. Companion-
   Service (schneller, Installationsschritt) — bestimmt, wie früh ort-web getestet wird.
3. Qualitäts-Schwelle für Go/No-Go des Studenten (z. B. graph-F1 ≥ 0.70 in-scope-32?).
