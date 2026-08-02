## 2026-08-02 — Testbox aufgeräumt (alle Foundry-Container/Volumes/Service weg); dabei 2 Bugs in `foundry_test_env.sh down` gefixt

**User: „clean up this box".** Der Aufräum-Lauf hat selbst zwei Fehler in der
Teardown-Funktion aufgedeckt — beide gefixt und verifiziert.

**Aufgeräumt (nichts davon lief noch):**
* Container `wac-foundry-test-{release,13,12}` (liefen 24–34 h) + Volumes
  `wac_foundry_test_data{,_release,_13,_12}` (das namenlose war ein Rest aus einem
  früheren Skript-Stand).
* Wall-Service auf `127.0.0.1:8177` (PID 3094977) gestoppt; Ports 8177/30000/30012/
  30013 sind frei.
* Scratch-Reste `/tmp/wac-{real,sm12,sm13}` + `/tmp/wac-arch-install.log`.
* systemd-User-Units: **keine** — `test_install_systemd.sh` hatte sich sauber
  abgeräumt (auch `Linger=no`), wie vorgesehen.

**Bug 1 — `down()` ließ Datenverzeichnisse liegen.** Es entfernte per Container nur
`bind-foreign`; die Verzeichnisse heißen aber `$BASE/$TAG-$MODE`, und die gehören je
nach Image-Generation 421/1000/root → `rm -rf` als User scheiterte, jeder der drei
`down`-Läufe endete mit „could not remove …" und `13-bind` blieb übrig. Jetzt: Löschen
per Container über **`$BASE/$TAG-*`** (nur der eigene Tag — `$BASE` wird von allen
Majors geteilt, ein `down --tag 13` darf v14-Daten nicht mitnehmen), Image dafür wird
aus lokal vorhandenen gewählt (`$IMAGE` → alpine → busybox, kein Pull), danach
`rmdir $BASE` sobald der letzte Tag weg ist. Status-Zeile sagte ebenfalls noch
`{bind,bind-foreign}` → auf `$TAG-<mode>` korrigiert.

**Bug 2 — „✓ container removed" war gelogen.** `docker rm -f` liefert **rc 0 auch für
einen nicht existierenden Container**, das `&& ok` feuerte also immer. Jetzt erst
`docker inspect`, dann Meldung (mit Namen). Gleiche Klasse wie die früheren
Verify-Lügen im Installer: Erfolgsmeldung ohne Beleg.

**Verifikation:** Failure-Case nachgebaut (Leftovers `13-bind` als 421 + `release-volume`
als root) → `down --tag 13` entfernt **nur** `13-*` und lässt `$BASE` stehen →
`down --tag release` entfernt den Rest **und** `$BASE`. Dazu `down` auf sauberer Box
(meldet nichts) und ein voller `up --tag 13 --mode volume` → `down`-Rundlauf: Container,
Volume, Datenverzeichnisse restlos weg. `bash -n` grün. Die vier Installer-Suiten sind
nicht betroffen (sie bauen ihre Container selbst, referenzieren `foundry_test_env.sh`
nur in einem Kommentar) → nicht erneut gefahren.

**Bewusst NICHT gelöscht (Platz ist da: 322 G von 3,7 T belegt):** Docker-Images
(felddy release/13/12 = 876 MB, Arch-Images ~2,1 GB) — ein Neu-Pull kostet nur Zeit;
und `corpus/heat_data_fa_inscope/` (692 MB, untracked, aus dem abgeschlossenen
HEAT-Arc). Beides auf Zuruf entfernbar.

---

## 2026-08-01 (später) — Fehlende Tests nachgeholt: systemd MIT echtem User-Bus (16/16), `--serve-module`-UI auf v13+v12, x86_64-Wheel-Frage beantwortet

**User: „If some tests are missing, please conduct them."** Drei Lücken waren übrig;
zwei sind jetzt geschlossen, eine bleibt physisch unmöglich.

**1. `systemctl --user` mit ECHTEM Session-Bus — neu `tools/test_install_systemd.sh`,
16/16 grün.** Läuft auf dieser Box (hat eine User-Session), pacman wird gestubbt,
alles andere ist der echte Pfad: Unit geschrieben → `enable` → von systemd gestartet →
Selftest („17 walls") → übersteht `systemctl --user restart` → Re-Run ist No-Op
(„already done, verified") → `--uninstall` stoppt und entfernt alles. Nebenwirkungen
sind eingegrenzt (Scratch-Repo in /tmp, Port 8188 statt 8177, Linger-Zustand wird
zurückgesetzt). Damit ist Stage 1 auf BEIDEN Wegen belegt: mit Bus (hier) und ohne
Bus (Container-Fallback).

**2. `--serve-module`-UI-Route auf v13 und v12 nachgezogen** (vorher nur v14): Docker
für den Installer geblockt (PATH-Stub), Manifest serviert, in Foundrys „Install
Module" eingetragen → beide melden **„Module wall-annotation-companion was installed
successfully"**, Dateien liegen im Container. **Wichtiger Nebenbefund:** der
Container-User unterscheidet sich je Image-Generation — **v12 = `foundry` (421)**,
**v13/v14 = `node` (1000)**. Genau deshalb chownt der Installer auf den Owner von
`Data/modules` statt auf eine feste uid; per docker-cp-Route auf v12 gegengeprüft:
Dateien landen als 421:421. (Meine ursprüngliche 421-Annahme war also für alte
Images richtig und für aktuelle falsch — die adaptive Lösung deckt beides.)

**3. x86_64-Wheel-Frage ohne x86_64-Box beantwortet (PyPI/Arch-API):** Arch liefert
aktuell **python 3.14.6**, onnxruntime 1.28.0 hat **cp311–cp314** manylinux-x86_64-
Wheels → auf dem Ziel sollte pip ein Wheel finden, die AUR-Sackgasse
[[arch-onnxruntime-not-official]] greift also voraussichtlich NICHT. Gut zu wissen,
bevor der User dort steht.

**Bleibende, ehrliche Lücken:** Vulkan/RX 6600 (keine AMD-GPU hier — physisch
unmöglich), Podman (nicht installiert; Codepfad geteilt mit Docker, aber ungetestet),
echte x86_64-Ausführung. In README §C.7a als Tabelle geführt.

---

## 2026-08-01 — STAGE 1 ENDLICH ECHT GETESTET (Arch-Container): 2 Installer-Bugs gefunden (pacman-Sandbox, verschluckte Fehler)

**User-Frage:** „Hast du das Testsystem genutzt, um fehlende Aspekte im Installations-
skript zu fixen?" → Ehrliche Antwort war: **nur für Stage 2** (Modul). Stage 1 (Service:
pacman/venv/wheels/Service/Selftest) war NIE gelaufen — weder hier noch beim User
erfolgreich. Also nachgeholt: **`tools/test_install_arch.sh`** fährt `install.sh` in
einem ECHTEN Arch-Container (`menci/archlinuxarm:base`, aarch64 — offizielles
archlinux-Image ist x86_64-only und es gibt kein binfmt/qemu auf dieser Box; Host-
binfmt registrieren = Eingriff ins User-System → nicht ohne Rückfrage).

**Was der Harness macht:** tracked files (Working-Tree-Inhalt, kein `git archive HEAD` —
sonst testet man den letzten Commit) in den Container, Modell vorlegen, `install.sh
--no-module --no-service` laufen lassen, dann Re-Run-No-Op, dann Selbstheilung
(.venv löschen → repariert sich), dann der systemd-Pfad ohne Session-Bus.

**🐞 BUG 1 — pacman 7 Landlock-Sandbox killt JEDE Transaktion.** In Umgebungen ohne
Landlock (Container, gehärtete/ältere Kernel) stirbt `pacman -Sy*` mit
„restricting filesystem access failed because the Landlock ruleset could not be
applied" → „switching to sandbox user 'alpm' failed" → „failed to synchronize all
databases". **Fix:** `pacman_try()` erkennt Landlock/sandbox/DownloadUser im Output und
wiederholt automatisch mit `--disable-sandbox` (+ Erklärung). Verifiziert: Warnung
erscheint, danach `✓ system packages`.

**🐞 BUG 2 — der Installer verschluckte pacman-Fehler.** Vorher sah der User nur
„pacman failed — check network / mirrors (see …log)". Bei einem Fehler auf einem
fremden Rechner (genau die Lage des Users, der KEINE Logs hat!) ist das nutzlos.
**Fix:** `log_mark`/`log_since` schneiden den Output der letzten Root-Aktion aus dem
Log, `pacman_report` druckt die letzten 8 echten Fehlerzeilen + wahrscheinliche
Ursachen (Netz/Mirror, unterbrochenes Teil-Upgrade → `sudo pacman -Syu`, Keyring →
`pacman-key --init/--populate`). Gegen einen kaputten Mirror getestet: man sieht jetzt
„Could not resolve host: nonexistent.invalid" im Terminal.

**🐞 BUG 3 — `user_systemd_available()` war blind.** Die Probe
`systemctl --user is-enabled default.target` antwortet **„static" mit rc=0, auch wenn
gar kein User-Bus erreichbar ist** (rein statische Unit-Metadaten). Folge: der
Installer wählte den systemd-Pfad, `daemon-reload/enable/restart` scheiterten still,
der Service startete nie → Abbruch am Schritt „service running" statt des vorgesehenen
Fallbacks. Genau das kann dem User über SSH/ohne Session passieren. **Fix:** Probe ist
jetzt `systemctl --user show-environment` (braucht den Bus; im Container rc=1, auf
einer echten Session rc=0 — beides gegengeprüft) **plus Defence-in-Depth:** schlagen
`daemon-reload/enable/restart` trotzdem fehl, fällt der Installer auf eine
Hintergrund-Instanz zurück statt den Schritt zu killen.

**🐞 BUG 4 — `verify_unit` hing an `diff`.** `diff` steckt in `diffutils`, das ein
minimales Arch NICHT zwingend hat (im Testcontainer fehlte es). Ohne `diff` schlug der
Vergleich IMMER fehl — mit der **falschen** Meldung „unit file outdated (path/port/
threads changed)" — und der Installer starb am systemd-Schritt direkt nachdem er die
Unit-Datei korrekt geschrieben hatte. **Fix:** reiner String-Vergleich
(`[ "$(unit_expected)" = "$(cat …)" ]`), keine externe Abhängigkeit mehr.

**Kosmetik mit Substanz:** die Abschluss-Zusammenfassung behauptete „Service runs as a
systemd user unit", auch wenn der Fallback lief. Jetzt merkt sich der Installer
`chosen.svcmode` (systemd|background) und schreibt die Wahrheit + „nach dem nächsten
Login einmal `systemctl --user enable --now …`".

**Bonus real verifiziert:** der **Modell-Download** (121,8 MB von mohammadi.eu) lief in
diesem Lauf zum ersten Mal auf Arch komplett durch (`✓ downloaded`).

**Ergebnis Stage 1 auf echtem Arch: grün** — pacman (mit Sandbox-Fallback),
venv, Wheels (onnxruntime/opencv/scikit-image real installiert), Port/Threads,
Service-Start, **Selftest „live detection works: 17 walls in 0.2s"**, Re-Run = No-Op,
Selbstheilung nach `.venv`-Löschung, systemd-Fallback (Unit-Datei wird korrekt
geschrieben: venv-Python, ConvNeXt-Modell, `--wall_thr 0.5`; ohne Session-Bus startet
er eine Hintergrund-Instanz und sagt dem User, was er nach dem nächsten Login tun soll).

**Ehrliche Grenzen (jetzt in README §C.7a als Tabelle):** `systemctl --user` mit echtem
Session-Bus ungetestet (Container hat keinen), Vulkan ungetestet (braucht RX 6600),
x86_64-Wheel-Verfügbarkeit für DAS Python des Users ungetestet (Testbox ist aarch64,
ALARM-Repos ≠ Arch-x86_64-Repos).

**Harness-Gotchas:** (a) Bash-Tool-Timeout (2 min) schnitt Läufe ab → sah aus wie ein
Hänger, war keiner. (b) **Detached/Hintergrund-Läufe des Arch-Harness werden im
letzten (längsten) Szenario gekillt** — dreimal exakt an derselben Stelle, Container
weg, keine Summary. Deshalb Harness im Vordergrund fahren; das systemd-Szenario habe
ich separat direkt gegen einen vorbereiteten Container verifiziert (grün: Unit
geschrieben, „systemd --user is not reachable" erkannt, Fallback auf
Hintergrund-Instanz, Selftest „17 walls", Summary sagt jetzt die Wahrheit).
(c) `pkill -f wall_service.py` in `docker exec bash -lc` trifft die eigene Shell
(Selbstmatch, CLAUDE.md-Gotcha) → im Harness mit Bracket-Pattern arbeiten.

---

## 2026-07-31 (spät) — IN-GAME-E2E auf Foundry v14 + v13 + v12 (alle 198 Wände); Ziel-Fehler antizipiert (onnxruntime-AUR-Falle, stopped-container, stale lock)

**User:** Testsystem laufen lassen, und **v13/v12 mitprüfen** (Ziel-Version unbekannt);
Logs gibt es nicht → **Fehler antizipieren**.

**✅ IN-GAME-E2E, drei Majors, echte Container, root-only named volume:**
| Foundry | Modul lädt | Toolbar-Button | Wände | Zeit |
|---|---|---|---|---|
| v14.365 | ja | ja (`tools` OBJECT) | **198** | 1.9 s |
| v13 | ja | ja (`tools` OBJECT) | **198** | 1.8 s |
| v12 | ja | ja (`tools` ARRAY) | **198** | 1.5 s |
Ablauf je Version: `foundry_test_env.sh up --tag X --real` → `seed` (minimales
System `walltest` + `maps/testmap.png` = headmasters-quarters 1280²) → `install.sh
--module-only --docker-container …` (docker-cp-Route) → `restart` → `foundry_ui_drive.py
e2e` (Welt anlegen, joinen, Modul aktivieren, Szene mit Hintergrund, `AutoWallCompanion
.detectWalls()`), Belege `docs/evidence/foundry-v1{2,3,4}-walls-detected.png`
(Wände-Layer aktiviert → Wände sichtbar; zeichnen Außenmauer inkl. Rundung + Nischen
sauber nach). Identische 198 Wände über alle Versionen = Modul/Service sind
versionsunabhängig, nur die UI-Anbindung unterscheidet sich.

**🔎 v14-BEFUND (wichtig, aber KEIN Bug heute):** v14 verschiebt den Szenen-Hintergrund
auf die neuen **Level**-Dokumente. `Scene#background` existiert nur noch als
Deprecation-Shim („Backwards-compatible support will be removed"). Der Shim liefert
den Level-`src` korrekt → **das Modul funktioniert auf v14**. Aber: Szene MUSS mit
`levels:[{background:{src}}]` erzeugt werden; das alte `background:{src}` wird auf v14
still ignoriert (src=null → Modul holt falsche URL → 404). Genau das war mein erster
Fehlschlag, kein Modulfehler. **Forward-looking TODO:** Modul soll künftig
`scene.levels`-Background lesen, sonst bricht v15/16.

**🐞 ANTIZIPIERTE ZIEL-FEHLER — gefunden + behoben:**
1. **onnxruntime-Fallback war eine Sackgasse.** `do_pydeps` fiel bei fehlenden Wheels
   auf `pacman -S python-onnxruntime python-opencv …` zurück — **`python-onnxruntime`
   ist NICHT in den offiziellen Arch-Repos** (nur AUR; via archlinux.org-API geprüft:
   opencv/numpy/scikit-image = extra, onnxruntime = fehlt). Auf einem rollenden Arch mit
   zu neuem Python (kein cp3XX-Wheel) wäre der Installer genau hier gestorben — ein
   sehr plausibler Kandidat für einen der ungenannten Fehler des Users. **Fix:**
   `arch_pkg_exists()` prüft per `pacman -Si`, installiert nur real existierende Pakete,
   und wenn onnxruntime danach fehlt → `need_user_action`-Pause mit AUR-Anleitung
   (`yay -S python-onnxruntime`), Alternative „venv mit älterem Python", Alternative
   „--pre probieren". Helper isoliert gegen einen pacman-Stub getestet.
2. **Gestoppter Foundry-Container ließ den Modul-Step hart scheitern** (docker-cp-Route
   brauchte `docker exec` für rm/mkdir/chown). Realistisch: User fährt Foundry runter,
   installiert, startet wieder. **Fix:** Sidecar-Container mountet dasselbe Volume und
   macht rm/cp/chown ohne exec und ohne Host-root; Verify liest module.json ebenso per
   Sidecar. Neuer Testfall T12 (Container per `docker create`, nie gestartet) grün.
3. **Stale Foundry-Lock nach Container-Restart.** `docker restart` unter Last hinterlässt
   `/data/Config/options.json.lock` → Foundry startet nicht mehr („already locked").
   Da WIR den Restart empfehlen, gehört das in die Doku: README-Troubleshooting-Zeile
   mit Ein-Zeiler zum Entfernen; `foundry_test_env.sh restart` räumt es automatisch.
4. **Service-URL bei Docker/anderem Gerät**: Modul ruft aus dem BROWSER → localhost gilt
   nur, wenn der Browser auf derselben Maschine läuft. Troubleshooting-Zeile ergänzt.
5. **Mehrere „foundry"-Container** → `--docker-container NAME` (in der Doku).

**Eigene Tooling-Bugs, die dabei auffielen (behoben):** `foundry_test_env.sh restart`
leitete den Volume-Mount aus `--mode` statt aus dem Container ab → löschte den Lock am
falschen Ort (jetzt: `docker inspect` der /data-Mount); Suite-Guards prüften nur
laufende Container, ein **gestoppter** Alt-Container kaperte T9 (jetzt `docker ps -a`).
`foundry_test_env.sh` kann jetzt `--tag release|13|12` (eigener Container/Volume/Port
pro Major: 30000/30013/30012) und `seed`/`restart`.

**Regression:** `tools/test_install_module.sh` **56/56** (inkl. T12), `test_install_nodocker.sh`
**25/25**, shellcheck clean (außer vorbestehendem SC2024).

**Playwright/v14-UI-Fallen (in foundry_ui_drive.py gelöst):** „Allow Sharing Usage
Data"-Dialog + Guided-Tour-Overlay fangen alle Klicks; Setup-Tabs sind
`<h2 data-tab=…>`, inaktiver Tab ist `display:none`; alle drei Panels teilen
`data-action=installPackage` → auf `#setup-packages-modules` scopen, sonst „does not
appear to point to a System"; v14 legt die Welt nach dem Anlegen sofort los
(auto-launch) und `/setup` leitet bei aktiver Welt um; v13/v12 nutzen `<select
name=system>`, v14 eine Karten-Auswahl + „Continue".

---

## 2026-07-31 (Abend) — ECHTES Foundry-Testsystem (v14 im Container) aufgesetzt; `--serve-module`-Route live bewiesen; PRIORITÄTS-BUG gefunden

**User:** „Can you set up a test system?" → ja, steht: **echtes, lizenziertes Foundry
v14.365 im Docker-Container** auf der Devbox (felddy/foundryvtt:release, arm64 zieht
sauber), plus zwei neue Tools:
- **`tools/foundry_test_env.sh`** — up/status/down, Modi `bind` (Volume gehört mir),
  `bind-foreign` (uid 421), `volume` (named volume, host-Pfad nur root); Flavour
  MOCK (echtes Image + echtes node + ECHTES argv `resources/app/main.mjs
  --port=30000 --headless --noupdate --dataPath=/data`, kein Lizenzbedarf) oder
  `--real` (echter Server). `status` zeigt u.a. genau den mountinfo-Pfad, den
  install.sh ohne Docker findet.
- **`tools/foundry_ui_drive.py`** — Playwright-Treiber (sign-eula, install-module
  --manifest URL, list-modules) mit Screenshots nach `corpus/results/foundry_ui/`.

**Credentials:** User hat Foundry-Login geschickt → liegen in `~/.foundry_test.json`
(chmod 600, **außerhalb** des Repos), als felddy-Secret nach `/run/secrets/config.json`
gemountet (damit NICHT in `docker inspect` sichtbar, anders als --env-file). Nie
ausgegeben, nie geloggt, nie committet. **→ Passwort wurde im Chat geteilt: User
soll es rotieren** (gleiche Empfehlung wie damals beim Forge-Passwort).

**🏆 DIE VORHER UNGETESTETE ROUTE IST JETZT ECHT BEWIESEN:** `install.sh
--serve-module` mit **geblocktem Docker** (PATH-Stub „permission denied on socket")
gegen den echten v14-Container mit **named volume (host-Pfad nur root)**:
Manifest-URL serviert (141.83.62.210:8399, Container konnte sie erreichen) → in
Foundrys „Add-on Modules → Install Module" eingetragen → Foundry-Konsole: **„Module
wall-annotation-companion was installed successfully"**; Installer erkannte Manifest-
und Zip-Fetch und beendete sich. Ground truth im Container: Dateien unter
`/data/Data/modules/wall-annotation-companion`, Owner **node:node (1000:1000)** =
Foundrys eigener User, v2.2.0. Screenshot-Beleg: `corpus/results/foundry_ui/
08-module-list.png` (Foundry v14 Build 365 listet „Wall Annotation Companion 2.2.0").
Auch die docker-cp-Route wurde gegen das ECHTE Image getestet (chown auf 1000:1000).

**🐞 PRIORITÄTS-BUG (nur durch das echte Testsystem gefunden, wäre dem User passiert):**
`install.sh --module-only` installierte in `~/AppData/Local/FoundryVTT/Data/modules`
— ein **Alt-Testverzeichnis** aus einer früheren Session —, WÄHREND Foundry im
Container lief. Ursache: Kandidatenliste mischte Belege und Rateversuche; der
`find $HOME`-Treffer bestand die „sieht wie Foundry-Data aus"-Prüfung und gewann,
bevor überhaupt nach dem Container gefragt wurde. **Fix:** Kandidaten sind jetzt in
zwei Klassen getrennt — `foundry_data_candidates_running` (dataPath eines laufenden
Host-Foundry + Container-Volume aus /proc/<pid>/mountinfo) vs.
`foundry_data_candidates_static` (options.json, Standardpfade, $HOME-Suche) —, und
die Reihenfolge in `do_foundry` ist: explizit → **laufende Instanz** → Container/
Runtime → statische Rateversuche (mit Herkunftshinweis + Warnung, wenn Foundry in
einem Container läuft) → root-Pfad → fragen/skippen. `foundry_modules_dir` nimmt
jetzt `running|static|all`.

**Kleinfix:** `host_addresses` gab docker0 doppelt aus (scope global + explizit) →
dedupliziert. Beide Suites haben jetzt einen Guard, der die Ausführung verweigert,
wenn ein fremder foundry-artiger Container läuft (sonst kapert er die Discovery —
genau das ist mir mit einem Probe-Container passiert).

**Regression:** `tools/test_install_module.sh` 51/51, `tools/test_install_nodocker.sh`
25/25, shellcheck clean (außer vorbestehendem SC2024).

**NOCH NICHT gemacht:** In-Game-Detection (Welt+System+Szene anlegen, „Detect Walls
(ML)" klicken) auf diesem v14-Container — die In-Game-Kette war zuletzt auf v13/Forge
mit dem mbv3-Modell verifiziert, nicht mit ConvNeXt auf v14. Testsystem steht dafür
bereit (`bash tools/foundry_test_env.sh up --mode volume --real`).

---

## 2026-07-31 (später) — Modul-Install OHNE Docker-Zugriff: /proc-Mount-Discovery + `--serve-module` (Foundry installiert selbst)

**User-Frage:** „Kannst du das Foundry-Modul auch OHNE Zugriff auf den Docker
installieren, wenn Foundry im Docker läuft?" → Antwort: **ja, in den meisten
Fällen sogar ganz ohne Docker UND ohne root.** Zwei neue Wege, beide gebaut+getestet.

**(1) Host-Pfad des Volumes aus dem Container-Prozess lesen — 0 Docker nötig.**
EMPIRISCH VERIFIZIERT auf dieser Box: `/proc/<pid>/mountinfo` eines
**root-eigenen** Container-Prozesses ist world-readable (`-r--r--r--`), und Feld 4
ist die Quelle jedes Mounts:
- Bind-Mount → direkt der Host-Pfad (`/tmp/x/fdata`)
- Named Volume → `/var/lib/docker/volumes/<name>/_data`
Neu: `container_volume_hostpaths()` + `mount_src_candidates()` (mappt Feld-4-Pfade
über maj:min gegen `/proc/self/mountinfo`, falls die Quell-FS anderswo gemountet
ist). Kandidaten fließen in `foundry_data_candidates` → wenn das Verzeichnis für
den User **schreibbar** ist (Normalfall `-v ~/foundrydata:/data`), wird das Modul
per simpler Dateikopie installiert: kein docker-Gruppe, kein sudo, kein Re-Login.
`foundry_modules_dir` jetzt **zweistufig** (erst „sieht wirklich wie Foundry-Data
aus": Data/modules + worlds|systems|Config, dann lockere Regel) — sonst konnte
das Volume eines FREMDEN Containers gewinnen (real passiert: mein eigener
Probe-Container hat N1/N2 zunächst gekapert → Testumgebung, aber der Fix ist echt).

**(2) `--serve-module`: Foundry installiert das Modul SELBST — weder Docker noch root.**
Foundrys „Add-on Modules → Install Module" nimmt eine **Manifest-URL**, lädt das
im Manifest-Feld `download` genannte Zip und entpackt es in seinen eigenen
Data-Ordner — als Container-User. Also: Installer serviert Zip + gepatchtes
module.json (`download` + `manifest` auf eine erreichbare Host-Adresse), druckt
die URL, und **erkennt am HTTP-Access-Log**, wann Foundry Manifest und Zip geholt
hat („Foundry downloaded the module archive"), dann Server-Stop. Wichtig:
NICHT `localhost` anbieten (im Container ist das der Container selbst) → routbare
Host-Adressen (`ip -4 -o addr`, docker0/podman0-Gateway, Hinweis auf
host.docker.internal). Manifest-Feld belegt: foundryvtt.com/article/module-development
(„download: A public URL that provides a zip archive … retrieved during the
installation or update process"). **Grenze, ehrlich:** dieser Weg ist von außen
nicht verifizierbar (kein Container-Zugriff) → Installer behauptet nicht „liegt
drin", sondern berichtet, was Foundry geholt hat. Mit einem ECHTEN, lizenzierten
Foundry-Image ist die UI-Seite nie getestet worden (Image ist gated).

**Route-Reihenfolge jetzt:** Host-Pfad schreibbar → Dateikopie · sonst Runtime
erreichbar → `docker cp` · sonst Host-Pfad bekannt aber nicht schreibbar → root
(sudo; Hinweis auf `--serve-module` als sudo-freie Alternative) · sonst Pause-Gate
mit 5 Optionen (A usermod+Re-Login, B `sudo -v`, C `--foundry-data`,
**D `--serve-module`**, E `--no-module`).

**User-Warnung beachtet (2026-07-31):** auf DIESER Box bin ich in der docker-
Gruppe, auf dem ZIEL evtl. nicht → alle „grünen" docker-cp-Tests sind mit Zugriff
gelaufen und sagen nichts über das Ziel. Belastbar für den Ziel-Fall ist NUR die
Stub-Suite (docker scheitert wie „permission denied on socket"). Daraus drei Fixes:
(a) der Heads-up am Anfang behauptete „stage 2 will ask you for one action", obwohl
die neue /proc-Route oft ohne alles durchläuft → jetzt nur noch, wenn Volume
NICHT schreibbar UND Runtime unerreichbar (sonst still); (b) sudo-Eskalation nennt
`--serve-module` als privilegienfreie Alternative; (c) interaktiver Prompt und
Skip-Zweig nennen `--serve-module` ebenfalls.

**Verifikation:** neu `tools/test_install_nodocker.sh` — **25 Assertions, alle
grün**, mit PATH-Stub, der `docker` wie „permission denied on socket" scheitern
lässt, bei ECHT laufendem Container: N1 Bind-Mount (mir gehörend) → Installation
ohne Docker/root, Dateien real da; N2 Named Volume (nur root) → Pause exit 4 +
`--serve-module` angeboten; N3 `--serve-module` → Manifest gepatcht+erreichbar
(nicht localhost), Zip ladbar, Download erkannt, Server sauber beendet (curl
spielt Foundry); N4 gar nichts erkennbar (kein Zugriff, kein sichtbarer Container)
→ Skip mit Rezept + `--serve-module`, exit 0 (Service-Install darf daran nicht
scheitern). Regression: `tools/test_install_module.sh` weiter **51/51 grün**.
shellcheck sauber (nur vorbestehendes SC2024), `bash -n` grün.

---

## 2026-07-31 — install.sh: Foundry-in-DOCKER support + echter Multi-Step-Handshake (User-Report: Installer scheiterte am Docker-Zugriff)

**User-Report vom Ziel-Arch-Rechner:** `bash install.sh` lief NICHT durch; u.a.
"keine Zugriffsrechte auf das Foundry-Docker". Frage des Users: habe ich Docker-
Zugriff (docker-Gruppe) angenommen? Und: nötige User-Aktionen sollen IM Skript
stehen, Installation soll mehrstufig sein.

**Root cause (bestätigt, nicht geraten):** `grep -i docker install.sh` = 0 Treffer.
Der Installer kannte Container GAR NICHT — er nahm ein *natives* lokales Foundry an,
dessen Data-Dir ein normales, für den User schreibbares Verzeichnis ist:
Discovery = (a) `pgrep` Foundry-Prozess + `--dataPath`, (b) host-`Config/options.json`,
(c) Standardpfade, (d) `find $HOME`; danach blankes `mkdir -p`/`unzip`.
Bei Foundry-in-Docker liegt das Data-Dir in einem **named volume**
(`/var/lib/docker/volumes/*/_data`, nur root → genau der gemeldete Fehler) oder in
einem Bind-Mount, das Foundrys Container-uid gehört (felddy: 421). Und *wo* es liegt,
weiß nur die Container-Runtime → Socket-Zugriff = docker-Gruppe oder sudo. Also:
nicht "docker-Gruppe angenommen", sondern **Container-Fall komplett übersehen**;
zusätzlicher Fallstrick: der `--dataPath` eines Container-Foundry (`/data`) ist ein
Pfad IM Container und auf dem Host bedeutungslos.

**Neu gebaut (install.sh 750 → ~1050 Zeilen):**
1. **Neuer Step `foundry` (Install-Ziel bestimmen)** vor dem Step `module`; Modus
   wird gemerkt (`chosen.modmode` = host|docker + `container`/`cdata`/`modparent`).
2. **Container-Erkennung OHNE Runtime-Zugriff:** `pid_in_container()` liest
   `/proc/<pid>/cgroup` der Foundry-Prozesse → wir wissen, dass Foundry im Container
   läuft, auch wenn wir nicht mit Docker sprechen dürfen. Container-`--dataPath`-
   Kandidaten werden jetzt bewusst VERWORFEN (Host-Pfad-Verwechslung).
3. **Routen-Wahl (billigste, die funktioniert):** Bind-Mount für uns schreibbar →
   normale Dateikopie; named volume / Bind-Mount gehört Container-uid → **über die
   Runtime** (`docker cp` + `chown -R <uid des Data/modules> ` im Container). Der
   zweite Fall braucht KEIN sudo — bewusst so, statt zu eskalieren.
4. **Multi-Step-Handshake `need_user_action()`:** Schritte, die nur ein Mensch
   erledigen kann, brechen nicht ab, sondern **pausieren** (exit 4) mit exakten
   Anweisungen + „danach einfach `bash install.sh`" (Resume genau dort). Marker
   `.install_state/blocked`; nächster Lauf meldet „resuming after: …".
   Docker-Gate nennt A) `sudo usermod -aG docker $USER` **+ ausdrücklich: aus- und
   wieder einloggen** (bzw. `newgrp docker`) — Gruppen gelten nur für neue Sessions,
   genau die Falle, an der ein simples „re-run" scheitert —, B) `sudo -v` (Installer
   nutzt dann `sudo docker`), C) `--foundry-data <hostpfad>`, D) `--no-module`.
5. **3 Stages sichtbar** (1 Service · 2 Modul-Dateien · 3 zwei Klicks in Foundry) mit
   Stage-Bannern; **Heads-up VOR Stage 1**, wenn erkennbar ist, dass Stage 2 eine
   Aktion braucht (User kann sie parallel machen). Neue Flags: `--module-only`,
   `--service-only`, `--docker-container NAME`.
6. **`--uninstall` container-sicher:** löscht im Docker-Modus IM Container
   (`docker exec rm -rf`) — vorher hätte ein Host-`rm -rf` auf einen Container-Pfad
   gezeigt (war durch `[ -d ]` abgefangen, aber falsch gedacht).
7. **Container-Restart-Hinweis** (`docker restart <name>`) statt „Foundry neu starten".
8. Nebenfix: `zip_module_json()` liest module.json via unzip ODER python-Fallback
   (id-Guard/Versionsvergleich hatten nur unzip).

**WICHTIG verifiziert (aus dem gelieferten `module.js`):** `detect()` macht
`fetch("http://localhost:8177/…")` **im Browser**, nicht im Foundry-Server → bei
Foundry-in-Docker bleibt die Service-URL `localhost:8177` korrekt, der Port muss
NICHT in den Container exponiert werden. Steht jetzt so in README §C.6 + im
Installer-Summary.

**Verifikation (H2/H8 — echte Container, keine Stubs): `tools/test_install_module.sh`,
51 Assertions, alle grün.** Fälle: named volume → docker cp; Bind-Mount schreibbar →
Host-Kopie; Bind-Mount uid 421 → docker cp OHNE sudo (Datei danach uid 421);
veraltete/verschmutzte Kopie → wird ersetzt statt gemerged (docker cp merged!);
kein Docker-Zugriff (PATH-Stub „permission denied on socket") + realer Container-
Foundry-Prozess → exit 4 + alle 4 Anweisungen + blocked-Marker + nichts installiert;
Resume danach grün; `--uninstall` löscht im Container, Container läuft weiter;
`--foundry-data` (Docker gar nicht angefasst); nicht schreibbares Dir → root-Pfad
(sudo simuliert, Testgrenze); kein Foundry → skip + Rezept, exit 0; `--status`.
shellcheck -S warning: nur die vorbestehende SC2024-Meldung (Log-Redirect gehört
absichtlich dem User). `bash -n` grün.

**Testgrenzen (ehrlich):** echtes root/`sudo` konnte hier nicht laufen (nur Stub),
pacman/systemd/Vulkan wie immer nicht (Ubuntu-aarch64-Devbox). Getestet wurde mit
`alpine`-Containern, nicht mit einem echten `felddy/foundryvtt`-Image.

**OFFEN / vom User gebraucht:** der Report nennt „One error was …" → es gab
MEHRERE Fehler. Ich habe nur den Docker-Fehler (rekonstruiert) gefixt. Für die
übrigen brauche ich `~/draw_maps/.install_state/install.log` bzw. die
Terminal-Ausgabe vom Ziel. Push zu GitHub = ask-first.

---

## 2026-07-24 (spät-3) — Clone-Deploy-E2E aus frischem Ordner: alles Testbare grün; 1 latenter unzip-Bug gefixt

**Auftrag (User):** frischen `git clone` in leeren Ordner, Modell ziehen, gründlich
durchdenken ob die Installation auf einem FREMDEN Arch-System (dem Zielrechner) läuft.

**Real ausgeführt (auf der Ubuntu-aarch64-Devbox, aus frischem Clone
`scratchpad/e2e_clone`) — alles grün:**
1. `git clone` GitHub → self-contained, 2 MB, sauber.
2. **Modell-Auto-Download vollständig verifiziert:** `http://mohammadi.eu/dateien/
   wall_student_convnext_tiny.onnx` → 301 auf `https://`; `curl -fL` (install.sh)
   folgt dem Redirect; 127 818 959 B (121.9 MB); **SHA256 == release-Konstante
   `461bb18f…2274fe` EXAKT**; ≥100 MB-Guard ok.
3. **Modul-Zip** `foundry_module/wall-annotation-companion.zip`: id `wall-annotation-
   companion`, v2.2.0, compat min12/verified14, enthält `scripts/module.js`+
   `module.json` → matcht MODULE_ID-Guard + `module_installed_ok`.
4. venv + `pip install -r requirements-service.txt` → alle Wheels lösen sauber
   (onnxruntime 1.27, opencv-headless 5.0, numpy 2.5, scikit-image 0.26). `verify_
   pydeps`-Import-Check (onnxruntime/cv2/numpy/skimage.skeletonize) ok.
5. Service mit EXAKT den Args aus `service_args()` (ONNX-Default) gestartet →
   `/health` = `{"status":"ok","model":"…convnext_tiny.onnx",…}` (matcht `verify_
   running`-grep) → `/detect` auf synthetischem Self-Test-Bild = **17 Wände/0.27s**
   (matcht `do_selftest`-JSON-Parse `count`/`elapsed_s`). Clone hat keine fa_tiles →
   Self-Test nimmt den synth-Pfad (genau der getestete).

**Nicht real ausführbar hier (Ubuntu, kein pacman/systemd/Vulkan) → statisch geprüft:**
sanity (pacman-Pflicht = hard-fail hier, auf Arch da; x86_64-Check nur warn),
pacman-Paketnamen alle offiziell (python/gcc-libs/glib2/curl/unzip/vulkan-radeon/
vulkan-icd-loader), venv/pip-Fallback-Kette (pip→--pre→Arch-Pakete), systemd-user+
linger, Foundry-Data-Discovery. Reihenfolge korrekt: pacman VOR model (→ curl da fürs
Download). Fazit: läuft auf dem Ziel.

**🐞 GEFIXT (latenter Bug, hätte „fully autonomous" auf minimalem Arch gebrochen):**
`do_module` id-Guard (Z.608) und `module_installed_ok` Versions-Vergleich (Z.593,
von `verify_module` genutzt) lesen die zip via `unzip -p` OHNE Fallback — während die
EXTRAKTION (Z.634) einen python-zipfile-Fallback hat. Ohne `unzip` stirbt `do_module`
am id-Guard, bevor der Fallback greift → Modul-Step (letzter Step) hard-fail. `unzip`
war NICHT in PKGS_BASE. **Fix: `unzip` zu PKGS_BASE hinzugefügt** (garantiert via
pacman, läuft vor dem Modul-Step). `bash -n` grün. Niedrige Wahrscheinlichkeit
(Desktop-Arch hat unzip fast sicher), aber sauber geschlossen. Lokal committet;
**Push zu GitHub = ask-first (noch offen).**

---

## 2026-07-24 (spät-2) — Rename → Wall Annotation Companion; README ersetzt INSTALL.md; Modell-Auto-Download; GitHub-Remote live

- **GITHUB-REMOTE (privat):** `https://github.com/esfandiar-mohammadi/draw_maps`
  (branch `main`). Token in `~/.git-credentials` (github.com-Zeile, credential.helper
  =store) → ich kann pushen ohne dass Token im Chat landet. Repo ist self-contained
  für Clone-Deploy (verifiziert): install.sh + pipeline/*.py + foundry_module/*.zip;
  Modell (122MB) git-ignored, wird gezogen (s.u.). Secret-Scan (Tree+History) sauber.
- **RENAME „Auto Wall Companion (ML)" → „Wall Annotation Companion"** (User: Name
  kollidiert mit Upstream ThreeHats/auto-wall-companion). Modul-id `auto-wall-
  companion-ml` → **`wall-annotation-companion`** v2.2.0. Quelle: src/module.json
  (id kommt via `import {id}` überall hin), package.json version, `npm run build`
  (node v24 @ ~/.nvm), neu gepackt. Nested-Repo-commit cd52942. Button „Detect Walls
  (ML)" + CSS-Klasse `auto-wall-dialog` ABSICHTLICH unverändert (Feature-Label, kein
  Produktname). install.sh MODULE_ID/Strings/Ordner/zip-Discovery angepasst; Modul
  landet in `Data/modules/wall-annotation-companion/` (Clone-getestet).
- **MODELL-AUTO-DOWNLOAD:** install.sh zieht das Modell automatisch von
  **http://mohammadi.eu/dateien/wall_student_convnext_tiny.onnx** wenn nirgends lokal
  gefunden (MODEL_DEFAULT_URL; nur onnx/CPU-Pfad, nicht --vulkan). --model-url/
  --model-src überschreiben. Download-Branch verifiziert (file://-Fetch, size+SHA).
- **DOCS:** neue **README.md** (deskriptiver Intro-Teil über das Tool + kompletter
  Install/Usage aus INSTALL.md, echte Clone-URL, Auto-Download; Credits ThreeHats/MIT).
  **INSTALL.md GELÖSCHT.** DEPLOYMENT.md + requirements-service.txt Referenzen
  INSTALL.md→README umgebogen. DEPLOYMENT.md bleibt (Modell/Qualität-Details).
- **STALE-ZIP-Bug (vorher, gefixt):** committete module.zip war Pre-Fix v2.0.0 (alte
  id) → jetzt korrekt. **foundry_module/*.zip ist die getrackte Deploy-Kopie**
  (vendor/ ist git-ignored → wäre sonst nicht im Clone). install.sh sucht
  foundry_module/ zuerst, dann vendor/ (rsync-Fall).

**DEPLOY-STAND: fertig & clone-deploybar.** Zielrechner (Arch, Ryzen3600/RX6600,
Foundry LOKAL): `git clone <url> ~/draw_maps && cd ~/draw_maps && bash install.sh`.
Das zieht Modell, installiert Service (systemd) + Foundry-Modul lokal, self-test.
Danach in Foundry 1× Modul aktivieren. OFFEN: nur der echte Lauf auf dem Arch-Ziel
(pacman/systemd/Vulkan konnten hier nie real laufen — Ubuntu-aarch64-Devbox).

---

## 2026-07-24 (später) — install.sh installiert auch das Foundry-Modul lokal + STALE-ZIP-Bug gefixt

User-Klarstellung: Zielrechner fährt Foundry LOKAL (kein Forge) → Modul-Install muss
auf demselben Rechner passieren, und der Installer soll (wie ursprünglich verlangt)
die lokalen Pfade dafür selbst finden. Zwei Sachen:

1. **STALE-ZIP-Bug gefunden (hätte User getroffen):** `vendor/auto-wall-companion/
   module.zip` (worauf INSTALL.md B.2 + meine frühere Antwort zeigten) war ein
   VOR-Fix-Build: id `auto-wall-companion` v2.0.0 = exakt die Kollision aus
   [[foundry-module-id-collision]] (Foundry-„Update" zieht archiviertes Upstream ohne
   ML). Korrektes Artefakt war `dist/` bzw. `awc-ml-2.1.0.zip` (id
   `auto-wall-companion-ml` v2.1.0). module.zip aus dist/ neu gebaut → jetzt korrekt
   (Modul-Repo commit fca6c1c). Merke: Verweis-Ziel VOR Deploy verifizieren, nicht
   nur dass „eine zip existiert".
2. **install.sh: neuer Step `module` (10. Step).** Findet Foundry-User-Data-Dir per
   (a) laufendem Prozess `--dataPath`, (b) `Config/options.json`-`dataPath`, (c)
   Standardpfaden (~/.local/share/FoundryVTT etc.), (d) bounded find nach `Data/
   modules`. Entpackt module.zip nach `<data>/Data/modules/auto-wall-companion-ml/`.
   Verify = id+version match gegen zip → outdated wird repariert. Kollisions-Guard:
   bricht ab, wenn die zip die falsche id trägt. Nicht gefunden → WARN+skip (nicht
   fatal; Service ist das Kritische) + Anleitung/`--foundry-data`. Foundry läuft →
   Warnung „neu starten". Enable+World bleibt 1× UI-Klick (per-world, unsafe während
   Foundry läuft; Service-URL-Default ist eh localhost:8177). Flags neu: `--no-module`,
   `--foundry-data DIR`. Uninstall entfernt Modul-Dir mit.
   **Getestet (7 Modul-Szenarien, alle grün):** explizit/auto-discovery(options.json &
   Prozess)/idempotent-skip/outdated-repair/not-found-skip/--no-module/collision-guard;
   + voller 10-Step-Lauf + resume(10 skip) + status + uninstall. shellcheck sauber.
   DEPLOYMENT.md §2 + INSTALL.md §C.2 aktualisiert (Modul jetzt auto; -ml-Ordnername).

**Konzept-Klarstellung an User:** der „lokale Server" (wall_service:8177) ist NICHT
Teil der Modul-Installation, sondern das permanente Runtime-Backend, das das Modul bei
jedem „Detect Walls (ML)" per HTTP anruft. Modul-Install (Dateien) und Service laufen
unabhängig.

---

## 2026-07-24 — install.sh: resumable Ein-Kommando-Installer (ersetzt deploy_arch.sh)

User will „nur Install drücken", ungetestbares Zielsystem (Arch x86_64, Kernel 7.1!,
zsh/Hyprland, Ryzen 3600/RX 6600). **`install.sh` (Repo-Root, `bash install.sh`)**
= verify-first-State-Machine: jeder Step ist (verify, do)-Paar; bei JEDEM Lauf wird
von vorn RE-verifiziert (State-File nur Hinweis, nie Wahrheit) → gesunde Steps in ms
übersprungen, kaputte repariert (= Rewind), dann weiter. `.install_state/` (git-ignored)
+ install.log. Flags: --status/--reset/--uninstall/--vulkan/--port/--host/--threads/
--model-src/--model-url/--no-service.

**Szenarien abgedeckt:** zsh/sh→bash-Re-Exec; Repo-Discovery; Modell-Suche (~,
Downloads, USB-Mounts) + SHA256 (Warn bei Retrain); sudo 3-Wege-Menü (Passwort /
„mach ich selbst im anderen Terminal"+warten / Abbruch) bzw. non-TTY→Befehl+exit 3
resumable; pacman: stale db.lck, -S→-Syu-Fallback; **Python-zu-neu→Wheels fehlen**
(Kernel 7.1!) → pip→pip --pre→pacman python-onnxruntime/-opencv/-scikit-image +
venv --system-site-packages; venv kaputt nach System-Python-Upgrade→Rebuild;
Port belegt→auto-advance (foreign) bzw. Restart (unser alter Service, /health-
Modellname geprüft!); Moduswechsel onnx↔vulkan invalidiert running+selftest korrekt;
systemd --user ohne Session-Bus→nohup-Fallback+Anleitung; Self-Test = echter
Detection-POST (Corpus-Tile oder synthetisiertes Bild).

**Der Test-Harness fand 4 ECHTE Bugs vor Deploy:** (1) **scikit-image fehlte in
requirements-service.txt** — graph_infer braucht skeletonize zur Laufzeit; auf
jungfräulichem Ziel wäre der Service SOFORT gecrasht (Dev-venv hatte es vom Training
→ nie aufgefallen; via Scratch-Repo+frischem venv gefunden; gefixt + Import-Check im
Installer). (2) port_free() gab immer true (Return-Wert des exec statt !-Test).
(3) `set -o pipefail` VOR dem bash-Guard → sh/dash starb vor Re-Exec. (4) --help-
sed-Range nach Reorder in Code gelaufen. Alles gefixt + regressionsgetestet
(pacman/loginctl gestubt, Rest ECHT: 11 Szenario-Tests grün, shellcheck sauber).
deploy_arch.sh gelöscht (superseded), INSTALL.md §A.2/§C.2 aktualisiert.

---

## 2026-07-23 (spät) — Autonomes Arch-Deploy-Script + Doku-Doublecheck (Deploy morgen)

User: „Modell fertig destilliert für Zielrechner? Doku doublechecken. Dann
vollautonomes Deploy-Script für Arch inkl. aller Libs/Deps." Alles erledigt.

- **Destillation FERTIG** — ConvNeXt-Tiny ONNX läuft CPU-only auf dem Ziel (kein
  GPU/ROCm). Nichts offen. Peak-RAM gemessen: **~750 MB** @1024² (baseline ~338 MB).
- **Doku-Doublecheck fand echten Bug:** `train_student.py --out` defaultet auf
  `wall_student_mbv3.pt` (KEIN Auto-Naming aus `--encoder`!). Meine Regen-Befehle
  ließen `--out` weg → hätten die mbv3-.pt überschrieben. In DEPLOYMENT.md,
  INSTALL.md (×2) und run_wall_service.sh `--out …tu_convnext_tiny.pt` ergänzt.
  Zusätzlich stale Zahlen in INSTALL-Intro/Prereqs gefixt (6.7M→32M, 26MB→122MB,
  ~1s→~2-2.5s Ryzen, RAM-Zeile auf gemessene ~750MB).
- **NEU `tools/deploy_arch.sh`** (vollautonom, idempotent): (1) Preflight
  (Arch/repo/python/sudo), (2) `pacman -Sy --needed` python git glib2 gcc-libs curl
  (+ vulkan-radeon/-icd-loader bei --vulkan; gcc-libs/glib2 = opencv-headless-
  Runtime), (3) Modell beschaffen (present / `--model-url` / `--model-src`; git-
  ignored, NICHT auf Ziel regenerierbar mangels CUDA → klarer Fehler + scp-Hinweis),
  (4) venv + `requirements-service.txt` + Import-Check auf DEN Wheels, (5) systemd-
  **user**-Unit + `enable-linger` (überlebt Logout/SSH; root→system-Unit-Fallback;
  systemctl-fehlschlag→Anleitung statt Abbruch), (6) Self-Test: /health + echter
  Detection-POST (Corpus-Tile oder synthetisiertes Bild). Flags: --port/--host/
  --threads(def 80% Kerne)/--vulkan/--no-service/--model-url/--model-src/--help.
- **Verifiziert (Ubuntu-aarch64-Devbox ist NICHT Arch → pacman/systemd gestubt,
  Rest ECHT):** onnx-Pfad 57 Wände/0.09s, --vulkan/ncnn 75/0.34s, missing-model-
  Fehlerpfad sauber, Thread-Calc 16/20=80%. pacman-Install + systemctl --user +
  Vulkan-GPU-Latenz sind die einzigen Teile, die NUR auf dem echten Arch-Ziel
  final laufen (dokumentiert). `bash -n` + Struktur ok.
- Docs: INSTALL.md §C.2 = „one command" (`bash tools/deploy_arch.sh`) + Manual-
  equivalent behalten.

---

## 2026-07-23 (nachts, später) — ConvNeXt-Tiny als Deployment-Default PROMOTED

User-Freigabe „Promote ConvNeXt-Tiny" abgearbeitet — die 5 Restschritte aus dem
RESUME-Block sind durch. **ConvNeXt-Tiny (0.765 @wall_thr 0.5) ist jetzt der
ausgelieferte Default** (ONNX/CPU). MobileNetV3 (0.741 @thr0.4) bleibt dokumentierter
Fallback.

1. **ncnn-Parität — FEHLGESCHLAGEN, sauber diagnostiziert + umgangen.** ncnn-Modell
   lud gar nicht (ONNX-Route: `ConstantOfShape`→malformed `MemoryData 0=512 1=512`,
   liest 262k Gewichte die nicht im .bin sind). Über **TorchScript-Trace** (pnnx' native
   Route) lud es → aber **all-NaN-Output**. Bisektiert: NaN entsteht in `convrelu_6`
   (simple 3×3-Conv im Decoder) → `inf`, UNABHÄNGIG von fp16 (fp32 identisch kaputt),
   Skip-Blob 311 konvertiert zu falscher 2D-Form. **= pnnx-Decoder-Miscompile spezifisch
   für die ConvNeXt-U-Net-Decoder-Struktur.** ONNX ist sauber (0.765 verifiziert).
   → **Entscheidung: ncnn/Vulkan bleibt MobileNetV3-only** (0.722, funktioniert).
   Kaputte ConvNeXt-ncnn-Dateien entfernt. Vulkan war ohnehin optionaler Speed-Pfad;
   ConvNeXt-CPU (~2-2.5s Ryzen) reicht fürs One-Shot-Import.
2. **`wall_service.py`:** `--wall_thr` (default 0.5) ergänzt, an `build_graph`
   durchgereicht; Default `--model`→ConvNeXt-onnx; `/health` nennt jetzt `wall_thr`;
   Usage-Kommentar aktualisiert. (build_graph-Default bleibt 0.4.)
3. **`tools/run_wall_service.sh`:** Modell→ConvNeXt-onnx, Regenerate-Hinweise aktualisiert.
4. **E2E reverify (beide Backends, echte Map `/tmp/claude-1000/testmap.png` 1396×2048):**
   ConvNeXt/ONNX-Default → **283 Wände in 0.84s** (JSON + UVTT beide grün, /health
   meldet convnext+thr0.5). MobileNetV3/ncnn-Fallback → 173 Wände in 0.59s (Beleg dass
   Fallback lebt). In-Game-Forge-E2E nicht wiederholt (Service-Pfad architektur-agnostisch,
   für mbv3 bereits verifiziert 2026-07-22).
5. **Docs:** DEPLOYMENT.md (Quality-Tabelle + §1 + §3) und INSTALL.md (§A.1 Modellbezug,
   §A.3/A.4/C.1/C.2/C.3/C.4/C.6, Troubleshooting, „Updating") auf ConvNeXt-Default +
   wall_thr-Konvention + ncnn-MobileNetV3-only-Warnung umgestellt.

Ruff: 5 Pre-existing-Style-Errors in wall_service.py (E401/E702, nicht von mir berührte
Zeilen) belassen — Codebase-weit toleriert. Nächste optionale Kür: ConvNeXt-Small (54M) /
DINOv2-ViT-S testen; Teacher weiter pushen bringt Student kaum (belegt). [[distill-student-capacity-ceiling]]

---

## 2026-07-23 (nachts) — KAPAZITÄT IST DIE DECKE: ConvNeXt-Tiny-Student 0.765 (+0.024)

User-Frage: „Zielsystem bekannt — wie viel Modell wagen? Smarteres Modell (Residual,
Dropout, LayerNorm, Attention)?" → **Budget-Analyse + entscheidendes Experiment.**
- **Budget:** One-Shot-Import-Tool → Latenz-Budget großzügig; RX 6600 hat 6.4GB
  nutzbar. Wir können ~5-10× Params auf CPU wagen, viel mehr auf Vulkan. Bindende
  Grenze = Deployment-Sauberkeit + Trainingskosten, NICHT die Hardware.
- **Hebel-Ranking (ehrlich):** Encoder-Kapazität = DER Hebel (Student underfittet,
  val-Dice-Plateau ~0.6). Attention nur sinnvoll via ViT-Encoder (nicht angeflanscht).
  Residual/Dropout/LayerNorm einzeln = marginal bzw. falsche Richtung (Dropout schadet
  bei Underfitting). ABER: ConvNeXts *Paket* (LayerNorm+7×7-depthwise+GELU) hilft real.
- **Experiment (train_student `--encoder`, bestehende Phase1-Pseudolabels):**
  | Student | Params | best graph-F1 |
  | MobileNetV3-L (shipped) | 6.7M | 0.741 |
  | EfficientNet-B4 | 20M | 0.740 |
  | **ConvNeXt-Tiny** | 32M | **0.765 @thr0.5** (P0.815 R0.736) |
  → **Kapazität IST die Decke** (widerlegt „nur bigger teacher"-Pessimismus von (5)).
  ConvNeXt-Tiny +0.024 über shipped, nur 0.021 unter Teacher (0.786). B4 ≈ shipped →
  es ist ARCHITEKTUR, nicht rohe Params.
- **Deployment-ready:** ONNX exportiert (Parität 4e-5, 122MB), 0.98s CPU@1024 dev
  (~2-2.5s Ryzen 3600, sub-1s RX6600 Vulkan). ONNX-graph-F1 = 0.765 (Parität bestätigt).
  Artefakte `wall_student_{tu_convnext_tiny.pt,convnext_tiny.onnx}` (git-ignored).
- **OFFEN (User-Entscheidung): ConvNeXt-Tiny als neuen Default promoten?** Tradeoff:
  +0.024 F1 für ~2× Latenz + 5× Modellgröße (26→122MB); braucht wall_thr=0.5 + ncnn-
  Re-Export + Re-Verify. shipped MobileNetV3 (0.741, E2E-verifiziert) bleibt bis
  Entscheidung Default. ConvNeXt-Small (54M) ungetestet = evtl. mehr. [[distill-student-capacity-ceiling]]

---

## 2026-07-23 — Qualitäts-Kür: INSTALL.md geschrieben; Student-Recall-Hebel WIDERLEGT

**User-Priorität (nach /clear, Antwort auf AskUserQuestion):** (1) Installations-
anleitung für Dritte + Zielsystem-Abschnitt, (2) Student-Recall, (3) Speed RX 6600,
(4) Teacher verbessern. Punkte (1)+(2) hier erledigt.

**(1) INSTALL.md (committet 7de1bc4)** — Dritt-Anleitung: Teil A Companion-Service
(clone→venv→`pipeline/requirements-service.txt`→`run_wall_service.sh`, Modell-Bezug
§A.1 da .onnx git-ignored), Teil B Modul (Manifest-URL / manuelles zip / aus Source;
Modul-ID-Kollisions-Warnung), B.4 Remote/Hosted-Foundry (cloudflared-HTTPS-Tunnel wie
im E2E), B.5 Konfig+Nutzung, Teil C Zielsystem (Ryzen 3600/RX 6600/Arch): CPU-only-
Begründung (gfx1032 ROCm-unsupported), 20%-frei-Budget (`--threads 9`), systemd-User-
Unit, Troubleshooting-Tabelle. Neu: `pipeline/requirements-service.txt` (onnxruntime/
opencv/numpy, getestete Versionen). Verifiziert: `/health`-JSON = Doku; Modul-Smoke grün.

**(2) STUDENT-RECALL-HEBEL EMPIRISCH WIDERLEGT (Hypothese refuted, H3).** Ziel war,
die P>R-Lücke (shipped P0.795 > R0.688) zu schließen. Zwei UNABHÄNGIGE Hebel getestet,
beide scheitern identisch — Recall sitzt bei ~0.69 fest:

| Config | P | R | F1 |
|---|---|---|---|
| **shipped (kein Tversky, thr0.4)** | **0.795** | 0.688 | **0.721** |
| Tversky β=0.7 w=1.0 | 0.771 | 0.688 | 0.715 |
| Tversky β=0.85 w=1.5 | 0.733 | 0.694 | 0.699 |
| shipped, thr0.30 | 0.782 | 0.691 | 0.720 |
| shipped, thr0.25 | 0.766 | 0.693 | 0.714 |
| shipped, thr0.20 | 0.734 | 0.694 | 0.696 |

- **Loss-Seite:** `train_student.py` um `--tversky_beta` erweitert (SMP-Konvention wie
  train_dino, beta→FN; committet 563519c). β=0.7 hob Mask-Dice 0.599→0.635, aber
  graph-Recall blieb EXAKT 0.688; nur Precision fiel → F1 runter. β=0.85/w1.5 noch
  schlechter (P-Kollaps).
- **Inferenz-Seite:** `graph_eval_student.py` um `--wall_thr` erweitert (committet a2acdc6).
  Schwellensenkung 0.4→0.2 auf shipped-Modell hebt Recall nur +0.011, Precision −0.060.
- **Root cause:** die verfehlten Wände erzeugen ~KEINE Modell-Response (nicht bloß
  schwache unter der Schwelle) → **Teacher-Blindstellen** (organische Kurven, Geröll),
  nicht Loss-/Threshold-behebbar. Recall-Gewinn MUSS vom Teacher kommen (Hebel #4
  DINO_IMPROVEMENT_PLAN → gratis Re-Distillation). [[training-patience-local-optima]]
- **Entscheidung:** shipped `wall_student_mbv3.{pt,onnx}` bleibt Champion (0.721),
  Experiment-Ckpts (`_recall.pt`,`_recall85.pt`) gelöscht (schlechter; git-ignored).
- **Behalten:** `--tversky_beta`/`--w_tversky` (student) + `--wall_thr` (eval) bleiben
  als Werkzeuge — nützlich, sobald ein besserer Teacher da ist.

**(3) SPEED RX 6600 — ncnn+Vulkan-Pfad GEBAUT + Qualität verifiziert (committet c15c21e).**
ROCm-frei (gfx1032 unsupported) via ncnn→Vulkan/RADV.
- ONNX→ncnn per **pnnx** (`inputshape=[1,3,1024,1024]`, fp16, 13MB param+bin).
  Netz ist voll-konvolutional, aber pnnx backt absolute Interp-Ausgabegröße (1024²)
  ein → Inferenz PADded Work-Bild (Längsseite ≤1024) auf 1024²-Quadrat, cropt zurück.
- **Qualität deployment-gleich:** ncnn-CPU graph-F1 **0.722** (P0.796 R0.684) vs
  ONNX 0.721; Masken-IoU ONNX-vs-ncnn 0.976, |diff|-mean 0.002. fp16 = Rauschen.
- Neu `pipeline/ncnn_eval.py` (torch-freie Graph-F1-Eval, ~287ms/Map fwd CPU hier).
  `wall_service.py`: `--backend {onnx,ncnn} [--vulkan]`; **train_seg/torch-Import
  raus** (IMEAN/ISTD inline) → Deploy-Service braucht kein torch mehr. Beide Backends
  E2E getestet (onnx 161 Wände/0.42s, ncnn 170/0.59s auf echter Map); /health nennt Backend.
  `graph_infer`: torch/smp jetzt lazy (build_graph torch-frei).
- **GOTCHA (aarch64-Dev-Box):** ncnn + skimage/torch OpenMP → nichtdeterministischer
  Segfault (ncnn im Loop). Fixes: onnxruntime VOR ncnn importieren (OpenMP-Stabilisator);
  ncnn-Eval in 2 Phasen (erst alle Forward-Passes, dann skimage/build_graph). Der
  x86-Zielrechner ist NICHT betroffen (bewiesen: Service-Backend E2E lief hier durch,
  ein Request pro Handler → kein Loop-Crash). [[user-target-hardware]]
- **NICHT verifiziert:** Vulkan-Latenz auf echter RX 6600 (Dev-Box hat keine
  Vulkan-GPU) → als Zielrechner-Schritt dokumentiert (INSTALL.md §C.6:
  `NCNN_VULKAN=1 ncnn_eval.py`). Qualitätsparität + CPU-Pfad SIND verifiziert.

**(4) TEACHER — Phase 0 Diagnostik → GRATIS +0.039 Teacher / +0.020 Student
(Vektorisierer-Fix, KEIN Retraining) (committet 5ee1f0c).**
- Neues Tool `pipeline/dino_phase0.py` (Plan Phase 0.1): teilt die 0.172-Lücke.
  Ergebnis in-scope-32: **MASK-UB** (skeletonisierte Roh-Maske vs GT) F1 0.777 R0.787
  vs **GRAPH** F1 0.728 R0.670 → der **Vektorisierer verliert ~0.12 Recall**, NICHT
  die Maske. Worst-R-Maps: old-owl-well 0.39, cave-gallery 0.46, fungi-cavern 0.54.
- **Root cause:** `drop_border_edges` (build_graph) warf pauschal JEDE randnahe Kante
  weg → löschte ECHTE Perimeter-Wände (Ruinen/Höhlen mit Wänden am Bildrand), nicht
  nur halluzinierte Rahmen. Beleg: Sweep auf gecachten Teacher-Masken (border_margin=0
  → 0.767).
- **Fix:** frame-aware `drop_border_edges(frame_frac=0.7)` — Kante nur droppen, wenn
  sie eine Randseite zu ≥70% überspannt (echter Rahmen); kurze reale Randwände bleiben.
  FREI für ALLE Pfade (build_graph geteilt): **Teacher MS 0.729→0.768**, **Student
  ONNX 1024 (DEPLOYED) 0.721→0.741** (R 0.683→0.722, P intakt 0.791), Student ncnn
  0.722→0.742. Per-Map: 24 besser / 1 schlechter (briny-maze −0.02) / 7 flat;
  Overlay bestätigt echte Perimeter-Wände (old-owl-well +0.17, `corpus/results/bm_overlays/`).
- **Korrigiert Befund (2):** Student-Recall war NICHT rein teacher-bound — ein Teil
  war vectorizer-bound (Border-Filter), gratis geholt. [[vectorizer-border-filter-recall]]
- **DEPLOYMENT.md aktualisiert** (Student 0.741, Teacher 0.768). `graph_eval_student`
  hat jetzt `--border_margin`.

**(5) PHASE 1 RETRAIN (User wählte "Phase 1 mask recall") — TEACHER 0.768→0.786
(+0.018) (committet 5114f05 Code; Ckpt `wall_dino_fa_p1.pt` git-ignored).**
Warm-start Champion + `--tversky_beta 0.7` + `--skeleton_recall` (neue
`soft_skeleton_recall`, MIC-DKFZ ECCV24; ersetzt clDice). Mask-val-Dice 0.632→0.659.
- **Erst schien Phase 1 zu verlieren** (default thr0.4: graph 0.761 < 0.768) — die
  Recall-Losses machten die Maske "fetter" (mask-recall 0.787→0.835), P fiel ~1:1.
- **wall_thr-Sweep drehte das Bild** (H3, nicht auf einem Betriebspunkt schließen):
  Phase1 hat die BESSERE Frontier. Fairer Vergleich (beide bester thr):
  Champion@thr0.5 = 0.776 vs **Phase1@thr0.7 = 0.786**. Phase1 dominiert bei jedem
  Recall-Level. Nebenbefund: **thr0.4 war für BEIDE suboptimal** (Champion 0.768→0.776
  @thr0.5). Aktueller Student: thr0.4 bleibt optimal (0.741; Frontier flacher).
- Teacher-Verlauf: 0.728 (orig) → 0.768 (frame-aware) → **0.786 (Phase1 @thr0.7)**.
- **Re-Distillation vom Phase1-Teacher FERTIG → Student-Gewinn NUR +0.003 (Rauschen).**
  `wall_student_mbv3_p1.pt` (aus `corpus/distill_pl_p1`): best über thr = **0.744
  @thr0.6** (P0.778 R0.737) vs shipped Student **0.741 @thr0.4**. Teacher +0.018,
  Student +0.003. **BEFUND: der 6.7M-MobileNetV3-Student ist KAPAZITÄTS-LIMITIERT**
  — er destilliert auf ~gleiches F1 egal wie gut der Teacher ist (wie schon beim
  Original: Student ~0.005 unter Teacher). Teacher-Verbesserungen erreichen den
  deploybaren Student NICHT mehr. [[distill-student-capacity-ceiling]]
- **ENTSCHEIDUNG: shipped Student bleibt Default** (0.741, verifiziert + in-game-E2E).
  +0.003 rechtfertigt kein Churn der E2E-getesteten Deployment. `wall_dino_fa_p1.pt`
  (0.786) + `wall_student_mbv3_p1.pt` (0.744) bleiben als Artefakte verfügbar.
- **KONSEQUENZ für Phase 2/3:** einen BESSEREN Teacher zu bauen bringt dem PRODUKT
  (Student) fast nichts mehr — Produkt-Gewinn bräuchte einen GRÖSSEREN Student, nicht
  besseren Teacher. Das sollte die Phase-2/3-Budget-Entscheidung leiten.

**OFFEN (Phase 2+, NIEDRIGERE Prio, Budget-Gate):** Auflösung 518+LoRA, OHEM/FDA.
Phase 3 (DINOv3, ControlNet) braucht User-Entscheidungen (Plan §5).

---

## 2026-07-22 (Nachmittag II) — ✅ IN-GAME-E2E in echter Foundry v13 BESTANDEN (letzter offener Schritt)

**Der einzige noch nicht in echter Foundry verifizierte Schritt ist jetzt hart belegt.**
Screenshot committet: `vendor/auto-wall-companion/test-evidence-v13-ml-detect.png`.

**Setup (User: Forge ist remote → Tunnel; cloudflared gewählt):**
- Headless-Browser-Harness aus Vorsession recovered (`scratchpad/forge/driver.py`,
  Playwright+Chromium; `state.json` = gespeicherte Session). Account-Session
  (`forge-vtt.com.sid`, gültig bis 28.07.) noch aktiv → **KEIN Passwort/Captcha
  nötig**, nur Foundry-Join als Gamemaster (leeres User-Passwort). Instanz:
  `eisenwind.forge-vtt.com`, Welt „Wall Test (Claude)", Foundry v13 Build 351.
- `cloudflared` (arm64) heruntergeladen → ephemerer HTTPS-Quick-Tunnel auf lokalen
  `wall_service` :8177. **HTTPS Pflicht** (Forge=HTTPS, Mixed-Content-Block sonst;
  localhost-Ausnahme greift nicht bei remote Browser).

**GOTCHA (gekostet: mehrere Runden) — Modul-ID-Kollision:** Modul-ID war
`auto-wall-companion` = archiviertes Upstream-Paket im Foundry-Registry. Foundrys
„Update" zog Upstream **1.2.2** (ohne ML) über den Fork; auch Install-by-URL wurde
überschattet. **Fix:** ID → `auto-wall-companion-ml` (v2.1.0), neu gebaut (npm,
smoke PASSED), als `awc-ml.json`+`awc-ml-2.1.0.zip` in die Forge-Asset-Library
hochgeladen (via `FilePicker.upload("forgevtt",...)` aus der authentifizierten
Seite), sauber per Manifest-URL installiert, alte ID im Welt-`moduleConfiguration`
deaktiviert, neue aktiviert. Fix im Modul-Repo committet (3eeebab) — **war ein
echter Bug, der auch den User getroffen hätte.** Nebenbei: die ML-Feature-Dateien
(`detect-walls.ts`, `module.ts`-Tool) waren aus dem Deadline-Sprint NIE ins
Modul-Git committet → jetzt nachgeholt.

**E2E-Ablauf (alles in echter Foundry-Canvas):** serviceUrl-Setting registriert
(default localhost:8177) → auf Tunnel-URL gesetzt → Szene „Wall Test Scene" mit
Wild-Crypt-Map bestückt (3600x3150, ppg150, padding0, alte 5 Test-Wände gelöscht)
→ Toolbar-Tool „Detect Walls (ML)" (unter Walls-Layer) ausgelöst → Dialog zeigt
korrekt die Tunnel-URL → „Detect walls" geklickt. **Ergebnis: 116 native
Wall-Dokumente** auf der Canvas, die die Crypt-Struktur (alle Raum-Perimeter,
Korridore, Sarkophag-Kammer) sauber nachzeichnen — deckungsgleich mit dem
Scripted-E2E-Overlay. Service-Log: `detect: 3600x3150 -> 116 walls in 0.49s`
(Request kam durchs Tunnel vom Browser). Coord-Transform (Pixel→Canvas) korrekt
bei padding0/grid=ppg.

**Danach aufgeräumt:** serviceUrl auf localhost:8177 zurückgesetzt (Tunnel war
ephemer), Tunnel+Service+Driver beendet. Welt bleibt mit ML-Fork aktiv, Crypt-Map
+116 Wänden als Demo. **Kein User-Passwort verwendet** (Session-State reichte).

**DAMIT: gesamte Kette end-to-end in echter Foundry verifiziert.** Offene Kür nur
noch Qualität (Recall-Hebel, DINO→0.9) — kein Verifikationsschritt mehr offen.

---

## 2026-07-22 (Nachmittag) — Autonome „continue"-Checks: _last vs best + Service-E2E auf Wild-Maps

Beide autonomen RESUME-Schritte (CLAUDE.md „continue" (1a)+(1b)) abgearbeitet.

**(1a) `_last.pt` (Ep16) vs best-Ckpt (Ep5) auf graph-F1, single-scale 1024, in-scope-32:**
`_last` MEAN P=0.806 R=0.680 **F1=0.725** vs shipped best 0.721 (single). Nur +0.004
→ innerhalb Rauschen, NICHT „deutlich besser" → **Entscheidung: shipped ONNX
(`wall_student_mbv3.onnx` aus best-Ckpt) bleibt Default, kein Re-Export.** (Mask-val-Dice
peakte Ep5=0.599, Ep16=0.569; graph-F1 ist zwischen Ep5/Ep16 praktisch flach — bestätigt,
dass die frühe Ckpt-Wahl korrekt war.) Log: `corpus/results/eval_student_last_1024.log`.

**(1b) Service-E2E OHNE Foundry, hart belegt.** Neues Tool `pipeline/service_e2e.py`:
lädt Wild-`.dd2vtt` (eingebettetes Battlemap + GT-Wände, nie im Training), extrahiert
das rohe Bild, POSTet es an den laufenden `wall_service` (:8177, /detect, single-scale
1024), rendert Overlay GRÜN=GT / ROT=Service-Prediction. Health-Check OK
(`{"status":"ok","model":"wall_student_mbv3.onnx","scales":"1024"}`). 3 Maps, 3 völlig
verschiedene Stile, je ~0.68–0.75s:
- `bm5501f_crypt` (photoreal dd2vtt, 3600x3150): GT=68 → PRED=115. Rot folgt Grün
  praktisch überall (alle Raum-Perimeter, Korridore, runde Sarkophag-Kammer); wenige
  Streuer im dunklen Rand. **Klares Success.**
- `test` (Cartoon/Scribble-Dungeon, 1280x1280): GT=197 → PRED=278. Organische Höhlen-
  Kontur + Innenwände + Truhen sauber getroffen; **Grid-Linien NICHT als Wände
  halluziniert** (HEATs Schwäche — Student clean).
- `tof5e_hilltop_ruins` (photoreal Outdoor-Ruine, 3750x3750, GT=8 → PRED=48):
  Out-of-scope-Stil; Student traced die Ruinen-Kontur + markiert paar Felsblöcke,
  halluziniert aber KEINE Wände im offenen Gras. Akzeptables Verhalten für Nicht-Ziel-Map.
Overlays: `corpus/results/service_e2e_{bm5501f_crypt,test,tof5e_hilltop_ruins}.png` (angesehen, H2).

**Fazit:** Deployment-Pfad (ONNX-Student → wall_service → editierbare Wand-Segmente)
end-to-end hart verifiziert auf ungesehenen Maps über 3 Stile. Einziger noch nicht in
echter Foundry verifizierter Schritt bleibt der In-Game-E2E (RESUME-Schritt 2, braucht
Forge+User).

---

## 2026-07-22 (Mittag) — ✅ SYSTEM FERTIG: Student 0.723 (Gate bestanden), ONNX+Service+Modul E2E

**Sprint durchgelaufen (~50 min gesamt dank fp16).** Ergebnisse in-scope-32 graph-F1:
- **Student MS = 0.723** (P0.795/R0.688), single = **0.721** — nur **0.005 unter
  Teacher 0.728**, bei ~180x Kompression (1.1B→6.7M). Gate (>=0.72) BESTANDEN.
- Single ≈ MS (0.721 vs 0.723) → Deployment nutzt **single-scale 1024** (3x
  schneller). fp32-ONNX-Parität exakt (0.721), 0.65s/Map hier.
- Overlays geprüft (corpus/results/student_overlays): water-town 0.78 sauber,
  worst old-owl-well 0.40 = Geröll-Ruine (Teacher-Schwäche getreu übernommen,
  kein neuer Defekt). Masken-Val-Dice peakte Ep5 0.599, dann flach ~0.57 (nah
  Teacher ~0.63) → best-Ckpt Ep5 gespeichert.

**INT8 VERWORFEN (belegt):** per-channel-QDQ kollabiert MobileNetV3 (hardswish/
hardsigmoid) auf graph-F1 **0.380** (fp32 0.721), trotz 0.32s vs 0.65s. → fp32
ausliefern; kein QAT vor Deadline. [[int8-mobilenetv3-collapse]]

**Deployment E2E gebaut+getestet:**
- ONNX-Export `pipeline/export_student_onnx.py` (fp32 26MB, opt-in --int8).
- graph_eval_student.py: **ONNX-Pfad** ergänzt (ckpt .onnx → onnxruntime;
  Deployment-Paritäts-Eval). fp32-ONNX = torch = 0.721 verifiziert.
- Service `pipeline/wall_service.py` (default jetzt single-scale) mit ECHTEM
  Modell getestet: water-town 483 Wände in 0.63s. Launcher `tools/run_wall_service.sh`.
- Modul `vendor/auto-wall-companion`: rebuild + smoke grün, `module.zip` (24KB) gepackt.
- `DEPLOYMENT.md` = Anleitung (Service starten, Modul installieren, re-distillieren).

**Zielhardware-Erwartung:** Ryzen 3600 (kein VNNI) ~2x langsamer → ~1.3s/Map
single-scale, CPU-only via onnxruntime (KEIN ROCm nötig — gfx1032 eh unsupported).

## 2026-07-22 (Mittag) — SPRINT BESCHLEUNIGT ~4.7x nachdem User RAM freigab

User gab GPU frei (CUDA free 28→82GB, Gemma geschrumpft) und fragte nach mehr
Parallelisierung. **Befund: Labeling war der kritische Pfad, GPU-Auslastung 96%
= compute-bound auf dem 1.1B-Teacher → größere Batches allein bringen wenig.**
Echter Hebel = **fp16-autocast des Teachers**: auf echter Map GEMESSEN 4.2x
(11.78s→2.79s), Soft-Labels praktisch identisch (wall |diff| mean 0.0002 / max
0.0065, >0.5-Agreement 99.98%) → keine Qualitätskosten. In Produktion mit bs32
+ weniger Gemma-Contention: **30.8 Maps/min statt 6.5** (~4.7x) → Restlauf
~14 min statt ~66. Peak nur 9.1GB bei bs24 (von 82GB).

Zweiter Gotcha bestätigt: **kein zweiter Teacher daneben ladbar** (contiguous-
Alloc OOM trotz freiem Speicher) → Benchmarks nur nach Stop des laufenden Jobs.
Sprint sauber gestoppt (141 fp32-Labels behalten, resumebar; gemischt fp32/fp16
für Distillation unkritisch) und mit fp16/bs32 neu gestartet.

Weitere Änderungen (Commit 9512565): Student-Training jetzt **AMP** (autocast+
GradScaler, smoke-getestet kein NaN mit fp16-clDice) + **bs128 + 12 workers +
prefetch**; **Gemma-Warte-Gate entfernt** (82GB frei → Training braucht kein
Warten). `distill_pseudolabel.py --fp16`, `train_student.py --amp/--workers`.

## 2026-07-22 (Vormittag) — P1-SPRINT GESTARTET: Deadline morgen Abend, System = Modul+Service+Student

**User-Entscheidungen:** Deadline **morgen (23.07.) Abend** fuer ein fertiges System;
"serverseitig" = lokaler Companion-Service, den das Foundry-Modul anspricht;
Go/No-Go-Schwelle Student **>=0.72** in-scope-32. User macht GPU frei (beendet Gemma) —
Sprint wartet darauf automatisch.

**Läuft (setsid, ueberlebt /clear): `tools/distill_sprint.sh`**, Log
`corpus/results/distill_sprint.log`. Stage 1a Pseudo-Labeling laeuft SOFORT neben
Gemma (bs=8, ~2.3 Maps/min unter Contention → ~3-4.5h); wartet dann auf Gemma-Exit
(pgrep auf gguf-Dateinamen, kein Selbstmatch); Stage 1b Nachzuegler-Sweep; Stage 2
Training `wall_student_mbv3.pt`; Stage 3 Eval single+MS auf in-scope-32 mit Overlays.

**Kern-Redesign ggue. Plan:** Die "176k Crops" waren 176k POOL-ZEILEN mit Duplikaten —
dedupliziert sind es **474 unlabeled VOLL-Maps** (drakkenheim 383 bis 12k×12k! +
ssl_real 83 + maps 8) + **147 FA-in-scope-TRAIN-Maps** (nie fa_test/outscope) =
621 Maps, alle mit dem exakten MS-Teacher-Protokoll (768/1024/1536, ref 1024 =
0.728-Betriebspunkt) gelabelt → `corpus/distill_pl/{images,soft}/` (soft-PNG:
ch0=wall, ch1=junc). Student trainiert auf Random-Crops 256–640px daraus (native
Skala der spaeteren 1024er-Inferenz) + harte Anker fa_tiles(0.25)/real(0.15)/
donjon-cap-8k(0.15). Loss BCE+MSE+0.4·clDice(wall)+BCE(junc)+node-reg; Val =
fa_tiles-Holdout (train_dino-Konvention), best-Dice-Checkpoint.

**Neue Dateien (committet a1d9b40):** `pipeline/distill_pseudolabel.py` (GEBATCHTE
Tile-Inferenz statt 1-Tile-Forwards, resumefaehig, OOM-Fallback bs4+Skip),
`pipeline/train_student.py`, `pipeline/graph_eval_student.py` (identisches Metrik-
Protokoll, aber 1 gepaddeter Forward/Skala statt 252er-Tiling; STUDENT_EVAL_DEV=cpu
moeglich; --fa_list default in-scope-32 → MEAN direkt vergleichbar),
`tools/distill_sprint.sh`, Listen `corpus/distill_{unlabeled,fa_train}.txt`.

**Gotchas dieser Runde:** (a) OpenCV imread verweigert WebP >64MB → env
`OPENCV_IMGCODECS_WEBP_MAX_FILE_SIZE=1073741824` (drakkenheim bis 130MB).
(b) Alter Warte-Loop aus Vorsession hing im pgrep-SELBSTMATCH (wartete ewig auf
train_dino…inscope_long) → gekillt; Launcher matcht deshalb auf den gguf-Dateinamen.
(c) Smoke-E2E verifiziert: pseudolabel(1 FA-Map, visuell geprueft: teacher-typisch
fette Soft-Waende + Moebel-Unsicherheit — build_graph schwellwertet das) →
train(48 samples, val-Dice 0.427) → graph_eval(1 Map CPU, F1 0.40). Mechanik ok.

**Foundry-Plan (morgen):** vendor/auto-wall-companion (v13-verifiziert) importiert
Wall-Arrays `{c:[x0,y0,x1,y1],…}` in die AKTUELLE Szene (processWallImport,
100er-Batches). Neuer Tool-Button "Detect walls (ML)": Szenen-Bild → POST
localhost-Service (http://localhost von https aus erlaubt, secure-context-Ausnahme;
CORS * im Service) → Walls in BILD-Pixeln → Modul rechnet Padding/Scale-Transform
(H7! sceneX/Y-Offsets, Unit-Test) → createEmbeddedDocuments. Service:
`pipeline/wall_service.py` (heute noch): Bild → Student (ONNX/torch) → build_graph
→ JSON; optional UVTT-Export mit grid_detect-ppg fuer Neu-Szenen-Flow.

## 2026-07-22 — Distillations-Recherche komplett; DISTILL_PLAN.md geschrieben (User waehlt)

**User-Richtung:** Fokus auf DINO (HEAT-Arc zu). Neuer Task: Modell auf User-Hardware
distillieren — **Ryzen 3600 + RX 6600 8GB (gfx1032!) + 16GB, Arch, 20% Reserve**,
Qualitaetsziel „aehnlich wie DINO-Pipeline" (0.728). User erinnerte ein Paper
„Entscheidungsbaum mit Conv-Filtern als Splits" → **IDENTIFIZIERT: Laptev & Buhmann,
GCPR 2014 Best Paper** (kein Code, kein Skalen-Praezedenzfall → Forschungs-Bet).

4 Research-Agents (Baeume / CNN-Student+KD+Deployment / Exoten / AMD-Verifikation),
alles in **`DISTILL_PLAN.md`**. Kernfakten: (a) Teacher direkt auf RX 6600 FRAGIL
(gfx1032 unsupported, HSA-Override ab ROCm 6.4.3 SIGSEGV-kaputt, ORT-ROCm-EP
entfernt, 8GB grenzwertig) → Distillation ist der robuste Weg. (b) Beste Studenten
lokal GEMESSEN: MobileNetV3-L-U-Net 6.7M = 0.63s @1024² nativ CPU (onnx+onnxruntime
jetzt im .venv). (c) KD-Rezept mit staerkstem Praezedenzfall: Output-Space-Distillation
mit Teacher-Pseudo-Labels auf den 176k unlabeled Crops (Depth Anything V2: Pseudo-
Labels SCHLAGEN manuelle; MobileSAM 110× „near-parity"). (d) Foundry: keine
COOP/COEP-Header → kein WASM-Threading; INT8 bringt in WASM keinen Compute-Gewinn;
WebGPU nur opportunistisch. (e) ROCm-freie GPU-Pfade fuer Studenten: ncnn+Vulkan
(RADV) nativ, WebGPU im Browser. Vorschlaege ranked: P1 CNN-Student (4-6 Tage bis
Go/No-Go), P2 Structured-Forest/GBT-Probe (User-Baum-Idee seriös, 1-2 Tage), P3
Guided-Filter+Kaskade-Multiplikator, P0 Teacher-direkt NICHT empfohlen.
Offen: User-Wahl P1/P2-Start, Browser-vs-Companion-Prio, Go/No-Go-Schwelle.

Zeitschaetzung DINO-Verbesserungsplan (User-Frage): Ph0 ~0.5d, Ph1 ~2-3d,
Ph2 ~1-1.5 Wo, Ph3 ~2-3 Wo → ~4-6 Wochen seriell bis 0.9-Versuch.

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
