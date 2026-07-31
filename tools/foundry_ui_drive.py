#!/usr/bin/env python3
"""Drive a local Foundry VTT (v13/v14) in a browser for end-to-end tests.

Used to verify the parts of the installer that can only be checked from
Foundry's own UI — above all the `install.sh --serve-module` hand-off, where
Foundry itself downloads and installs the module from a manifest URL.

    .venv/bin/python tools/foundry_ui_drive.py sign-eula
    .venv/bin/python tools/foundry_ui_drive.py install-module --manifest URL
    .venv/bin/python tools/foundry_ui_drive.py list-modules

Options: --url (default http://127.0.0.1:30000), --headed, --shots DIR.
Screenshots of every step land in --shots (default corpus/results/foundry_ui/).
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

SHOTS = pathlib.Path("corpus/results/foundry_ui")


def shot(page, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    p = SHOTS / f"{name}.png"
    page.screenshot(path=str(p), full_page=False)
    print(f"    shot: {p}")


def dismiss_dialogs(page) -> None:
    """Clear Foundry's first-run prompts that intercept pointer events.

    v14 opens an "Allow Sharing Usage Data" dialog on the first /setup visit; it
    covers the panels, so every later click retries forever. Telemetry is
    declined — this is the user's own instance.
    """
    for _ in range(4):
        dlg = page.locator("dialog[open]").first
        if not dlg.count():
            return
        for sel in ('button:has-text("Decline Sharing")', 'button:has-text("Decline")',
                    'dialog[open] header a.close', 'dialog[open] button.close',
                    'dialog[open] [data-action="close"]'):
            b = page.locator(sel).first
            if b.count() and b.is_visible():
                b.click()
                print(f"  dismissed dialog via {sel}")
                time.sleep(1)
                break
        else:
            try:
                page.keyboard.press("Escape")
                time.sleep(1)
            except Exception:
                return


def dismiss_tours(page) -> None:
    """Close Foundry v14's first-run guided tour.

    Its `div.tour-overlay` sits above the setup panels and swallows every click,
    so Playwright retries until it times out.
    """
    for _ in range(6):
        if not page.locator("div.tour-overlay, .tour").first.count():
            return
        for sel in ('.tour [data-action="exit"]', '.tour button.exit',
                    '.tour a.close', 'button:has-text("Exit Tour")',
                    'button:has-text("Skip")'):
            b = page.locator(sel).first
            if b.count() and b.is_visible():
                b.click()
                print(f"  exited tour via {sel}")
                time.sleep(1)
                break
        else:
            page.keyboard.press("Escape")
            time.sleep(0.8)
    if page.locator("div.tour-overlay").first.count():
        # last resort for a headless test run: take the overlay out of the way
        page.evaluate("document.querySelectorAll('.tour-overlay,.tour').forEach(e => e.remove())")
        print("  removed the tour overlay from the DOM (headless test)")


def sign_eula(page, url: str) -> bool:
    page.goto(f"{url}/license", wait_until="networkidle")
    shot(page, "01-license")
    if "/license" not in page.url:
        print("  licence already signed")
        return True
    # v13/v14: a EULA form with an agree checkbox and a submit button
    for sel in ('input[name="agree"]', "#eula-agree", 'input[type="checkbox"]'):
        box = page.locator(sel).first
        if box.count() and box.is_visible():
            box.check()
            print(f"  checked {sel}")
            break
    for sel in ('button[name="agree"]', 'button:has-text("Agree")',
                'button[type="submit"]', "#sign"):
        btn = page.locator(sel).first
        if btn.count() and btn.is_visible():
            btn.click()
            print(f"  clicked {sel}")
            break
    else:
        print("  !! no agree button found", file=sys.stderr)
        return False
    for _ in range(40):
        time.sleep(0.5)
        if "/license" not in page.url:
            break
    shot(page, "02-after-license")
    print(f"  now at {page.url}")
    return "/license" not in page.url


def install_module(page, url: str, manifest: str) -> bool:
    page.goto(f"{url}/setup", wait_until="networkidle")
    time.sleep(2)
    shot(page, "03-setup")
    dismiss_dialogs(page)
    dismiss_tours(page)
    shot(page, "03b-setup-clear")
    # Open the Add-on Modules tab. In v14 the setup tabs are <h2 class="divider"
    # data-tab="worlds|systems|modules"> — NOT anchors, and the inactive tab
    # section is display:none, so its Install button is present but unclickable.
    for sel in ('h2[data-tab="modules"]', '[data-tab="modules"]:not(section)',
                'h2:has-text("Add-on Modules")'):
        t = page.locator(sel).first
        if t.count() and t.is_visible():
            t.click()
            time.sleep(1.5)
            print(f"  opened the modules tab via {sel}")
            break
    dismiss_tours(page)
    shot(page, "04-modules-tab")
    # IMPORTANT: v14's setup page has one install button per panel (worlds,
    # systems, modules) all sharing data-action="installPackage". Scope it to
    # #setup-packages-modules, or you open the *system* installer and Foundry
    # answers "The provided URL does not appear to point to a System."
    for sel in ('#setup-packages-modules button[data-action="installPackage"]',
                '#setup-packages-modules button:has-text("Install Module")',
                'button:has-text("Install Module")'):
        b = page.locator(sel).first
        if b.count() and b.is_visible():
            b.click()
            print(f"  clicked {sel}")
            time.sleep(1.5)
            break
    else:
        print("  !! no Install Module button", file=sys.stderr)
        return False
    shot(page, "05-install-dialog")
    field = None
    for sel in ('input[name="manifestURL"]', 'input[placeholder*="Manifest"]',
                'input[name="manifest"]', 'dialog input[type="text"]'):
        f = page.locator(sel).first
        if f.count() and f.is_visible():
            field = f
            print(f"  manifest field: {sel}")
            break
    if field is None:
        print("  !! no manifest URL field", file=sys.stderr)
        return False
    field.fill(manifest)
    shot(page, "06-manifest-filled")
    for sel in ('button:has-text("Install")', 'button[type="submit"]',
                '[data-action="install"]'):
        b = page.locator(sel).last
        if b.count() and b.is_visible():
            b.click()
            print(f"  clicked {sel}")
            break
    # Foundry shows a notification and the package appears in the list
    ok = False
    for _ in range(60):
        time.sleep(0.5)
        body = page.content()
        if "wall-annotation-companion" in body or "Wall Annotation Companion" in body:
            ok = True
            break
    time.sleep(2)
    shot(page, "07-after-install")
    return ok


def list_modules(page, url: str) -> list[str]:
    page.goto(f"{url}/setup", wait_until="networkidle")
    # the setup screen renders client-side; without this wait the screenshot is
    # just the splash background and the list looks empty
    page.wait_for_selector("#setup-packages", timeout=30000)
    time.sleep(2)
    dismiss_dialogs(page)
    dismiss_tours(page)
    for sel in ('h2[data-tab="modules"]', 'h2:has-text("Add-on Modules")'):
        t = page.locator(sel).first
        if t.count() and t.is_visible():
            t.click()
            time.sleep(2)
            break
    page.wait_for_selector("#modules-list", timeout=15000)
    shot(page, "08-module-list")
    return page.evaluate("""() => [...document.querySelectorAll('#modules-list [data-package-id]')]
        .map(e => e.dataset.packageId + ' — ' + (e.querySelector('.package-title,h3,.title')?.textContent || '').trim())""")


def create_world(page, url: str, system: str, title: str) -> bool:
    page.goto(f"{url}/setup", wait_until="networkidle")
    time.sleep(2)
    # With a world already active, Foundry redirects /setup to /join or /game.
    if "/setup" not in page.url:
        print(f"  a world is already active (at {page.url}) — skipping creation")
        return True
    try:
        page.wait_for_selector("#setup-packages", timeout=30000)
    except Exception:
        print(f"  setup page did not render (at {page.url})", file=sys.stderr)
        return "/join" in page.url or "/game" in page.url
    time.sleep(2)
    dismiss_dialogs(page)
    dismiss_tours(page)
    existing = page.evaluate(
        "[...document.querySelectorAll('#worlds-list [data-package-id]')].map(e => e.dataset.packageId)")
    if existing:
        print(f"  world already present: {existing}")
        return True
    for sel in ('#setup-packages-worlds button[data-action="worldCreate"]',
                'button:has-text("Create World")'):
        b = page.locator(sel).first
        if b.count() and b.is_visible():
            b.click()
            print(f"  clicked {sel}")
            time.sleep(2)
            break
    else:
        print("  !! no Create World button", file=sys.stderr)
        return False
    shot(page, "10-world-dialog")
    for sel in ('input[name="title"]', 'input[name="name"]'):
        f = page.locator(sel).first
        if f.count() and f.is_visible():
            f.fill(title)
            break
    # v14 picks the system from a card list, older versions use a <select>
    sysel = page.locator('select[name="system"]').first
    if sysel.count() and sysel.is_visible():
        sysel.select_option(system)
        print(f"  system via <select>: {system}")
    else:
        for sel in (f'dialog [data-package-id="{system}"]', f'[data-package-id="{system}"]',
                    f'.package:has-text("{system}")'):
            card = page.locator(sel).first
            if card.count() and card.is_visible():
                card.click()
                print(f"  system via card: {sel}")
                time.sleep(0.8)
                break
        else:
            print(f"  !! system '{system}' not selectable", file=sys.stderr)
            return False
    for sel in ('button:has-text("Continue")', 'button[data-action="createWorld"]',
                'dialog button:has-text("Create World")',
                'form button[type="submit"]', 'button:has-text("Create")'):
        b = page.locator(sel).last
        if b.count() and b.is_visible():
            b.click()
            print(f"  submitted via {sel}")
            break
    # v14 LAUNCHES the new world right away, so the setup page we were polling is
    # gone — accept any of: it shows up in the world list, or we ended up in the
    # join screen / in the game itself.
    for _ in range(120):
        time.sleep(0.5)
        if "/join" in page.url or "/game" in page.url:
            print(f"  world created and launched (now at {page.url})")
            shot(page, "11-world-created")
            return True
        try:
            got = page.evaluate(
                "[...document.querySelectorAll('#worlds-list [data-package-id]')].map(e => e.dataset.packageId)")
        except Exception:
            continue
        if got:
            print(f"  world created: {got}")
            shot(page, "11-world-created")
            return True
    shot(page, "11-world-failed")
    return False


def launch_and_join(page, url: str) -> bool:
    # already inside the game (v14 auto-launch) or at the join screen?
    try:
        if page.evaluate("!!(window.game && game.ready)"):
            print("  already in the game")
            shot(page, "13-in-game")
            return True
    except Exception:
        pass
    if "/join" in page.url:
        return join_screen(page)
    page.goto(f"{url}/setup", wait_until="networkidle")
    page.wait_for_selector("#setup-packages", timeout=30000)
    time.sleep(1.5)
    dismiss_dialogs(page)
    dismiss_tours(page)
    wid = page.evaluate(
        "(document.querySelector('#worlds-list [data-package-id]')||{}).dataset?.packageId")
    if not wid:
        print("  !! no world to launch", file=sys.stderr)
        return False
    # launching by UI needs hover menus; the world launch endpoint is what the
    # button posts to, and it is stable across v12-v14
    page.evaluate("""async (wid) => {
        const r = await fetch('/setup', {method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'launchWorld', world: wid})});
        return r.status;
    }""", wid)
    for _ in range(60):
        time.sleep(1)
        page.goto(f"{url}/join", wait_until="domcontentloaded")
        if "/join" in page.url:
            break
    return join_screen(page)


def join_screen(page) -> bool:
    time.sleep(2)
    shot(page, "12-join")
    sel_user = page.locator('select[name="userid"]').first
    if sel_user.count():
        opts = page.evaluate(
            """() => [...document.querySelectorAll('select[name="userid"] option')]
                    .map(o => [o.value, o.textContent.trim()])""")
        gm = next((v for v, t in opts if t and "amemaster" in t), None) or \
             next((v for v, t in opts if v), None)
        if gm:
            sel_user.select_option(gm)
            print(f"  joining as {gm}")
    for sel in ('button[name="join"]', 'button:has-text("Join Game Session")',
                'button[type="submit"]'):
        b = page.locator(sel).first
        if b.count() and b.is_visible():
            b.click()
            print(f"  clicked {sel}")
            break
    for _ in range(90):
        time.sleep(1)
        if page.evaluate("!!(window.game && game.ready)"):
            print("  game is ready")
            shot(page, "13-in-game")
            return True
    shot(page, "13-join-failed")
    return False


def enable_module(page, url: str, module_id: str) -> bool:
    """Enable the module the same way the Manage Modules checkbox does."""
    enabled = page.evaluate("""async (id) => {
        const cfg = foundry.utils.deepClone(game.settings.get("core", "moduleConfiguration")) || {};
        if (cfg[id] === true) return "already";
        cfg[id] = true;
        await game.settings.set("core", "moduleConfiguration", cfg);
        return "set";
    }""", module_id)
    print(f"  moduleConfiguration: {enabled}")
    page.reload(wait_until="domcontentloaded")
    for _ in range(90):
        time.sleep(1)
        if page.evaluate("!!(window.game && game.ready)"):
            break
    active = page.evaluate("(id) => !!game.modules.get(id)?.active", module_id)
    api = page.evaluate("() => !!window.AutoWallCompanion")
    print(f"  module active: {active}   module API exposed: {api}")
    # the toolbar button is registered differently on v12 (array of tools) and
    # v13+ (object keyed by name) — check the tool really landed in the Walls
    # control, since that is what a user clicks
    tb = page.evaluate("""() => {
        const c = ui.controls?.controls;
        const walls = Array.isArray(c) ? c.find(x => x.name === "walls") : c?.walls;
        const tools = walls?.tools;
        const names = Array.isArray(tools) ? tools.map(t => t.name) : Object.keys(tools || {});
        return {shape: Array.isArray(tools) ? "array" : "object",
                hasDetectButton: names.includes("detect-walls-ml"), tools: names};
    }""")
    print(f"  toolbar: {tb['shape']}, Detect Walls (ML) present: {tb['hasDetectButton']}")
    shot(page, "14-module-enabled")
    return bool(active and api and tb["hasDetectButton"])


def make_scene_and_detect(page, service: str, map_rel: str) -> dict:
    # Version-critical: v14 moved the background onto Level documents. Passing
    # background.src at scene level is silently ignored there (src stays null and
    # the module then fetches the wrong URL — a 404). v12/v13 have no Level, so
    # the old shape is required. Foundry's deprecated scene.background shim DOES
    # report the level's src, which is why the module itself still works on v14.
    info = page.evaluate("""async (mapRel) => {
        const dims = await new Promise(res => {
            const im = new Image();
            im.onload = () => res({w: im.naturalWidth, h: im.naturalHeight});
            im.onerror = () => res({w: 2000, h: 2000});
            im.src = '/' + mapRel;
        });
        const name = "Wall E2E";
        const old = game.scenes.find(s => s.name === name);
        if (old) await old.delete();            // throwaway test world: keep it deterministic
        const hasLevels = !!CONFIG.Level?.documentClass;
        const base = {name, width: dims.w, height: dims.h, padding: 0, grid: {size: 100}};
        const data = hasLevels
            ? {...base, levels: [{name: "Ground", background: {src: mapRel}}]}
            : {...base, background: {src: mapRel}};
        const sc = await Scene.create(data);
        await sc.activate();
        await sc.view();
        return {sceneId: sc.id, w: dims.w, h: dims.h, levelsApi: hasLevels,
                backgroundSrc: sc.background?.src ?? null, wallsBefore: sc.walls.size};
    }""", map_rel)
    print(f"  scene: {info}")
    for _ in range(60):
        time.sleep(1)
        if page.evaluate("!!(canvas && canvas.ready)"):
            break
    page.evaluate("(u) => game.settings.set('wall-annotation-companion', 'serviceUrl', u)", service)
    shot(page, "15-scene-before")
    t0 = time.time()
    res = page.evaluate("""async () => {
        try {
            await window.AutoWallCompanion.detectWalls();
            return {ok: true, walls: canvas.scene.walls.size};
        } catch (e) {
            return {ok: false, error: String(e), walls: canvas.scene.walls.size};
        }
    }""")
    res["seconds"] = round(time.time() - t0, 1)
    time.sleep(3)
    shot(page, "16-scene-after-detect")
    # walls are only rendered while the walls layer is active — that is the shot
    # that actually shows what was detected
    try:
        page.evaluate("() => { canvas.walls.activate(); ui.notifications?.clear?.(); }")
        time.sleep(2.5)
        shot(page, "17-walls-layer")
    except Exception as e:
        print(f"  (could not activate the walls layer: {e})")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["sign-eula", "install-module", "list-modules", "e2e"])
    ap.add_argument("--url", default="http://127.0.0.1:30000")
    ap.add_argument("--manifest")
    ap.add_argument("--service", default="http://localhost:8177")
    ap.add_argument("--map", default="maps/testmap.png")
    ap.add_argument("--system", default="walltest")
    ap.add_argument("--world", default="Wall E2E World")
    ap.add_argument("--module-id", default="wall-annotation-companion")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--shots")
    a = ap.parse_args()
    global SHOTS
    if a.shots:
        SHOTS = pathlib.Path(a.shots)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not a.headed)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("console", lambda m: print(f"    [console:{m.type}] {m.text[:160]}"))
        try:
            if a.action == "sign-eula":
                rc = 0 if sign_eula(page, a.url) else 1
            elif a.action == "install-module":
                if not a.manifest:
                    print("--manifest is required", file=sys.stderr)
                    return 2
                sign_eula(page, a.url)
                rc = 0 if install_module(page, a.url, a.manifest) else 1
            elif a.action == "e2e":
                rc = 0
                print("[1/5] licence")
                sign_eula(page, a.url)
                print("[2/5] world")
                if not create_world(page, a.url, a.system, a.world):
                    return 1
                print("[3/5] launch + join")
                if not launch_and_join(page, a.url):
                    return 1
                print("[4/5] enable the module")
                if not enable_module(page, a.url, a.module_id):
                    return 1
                print("[5/5] scene + wall detection")
                res = make_scene_and_detect(page, a.service, a.map)
                print(f"  RESULT: {res}")
                rc = 0 if res.get("ok") and res.get("walls", 0) > 0 else 1
            else:
                mods = list_modules(page, a.url)
                print("  modules:", mods)
                rc = 0
        finally:
            browser.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
