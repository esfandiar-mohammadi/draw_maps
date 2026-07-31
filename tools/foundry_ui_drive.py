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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["sign-eula", "install-module", "list-modules"])
    ap.add_argument("--url", default="http://127.0.0.1:30000")
    ap.add_argument("--manifest")
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
            else:
                mods = list_modules(page, a.url)
                print("  modules:", mods)
                rc = 0
        finally:
            browser.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
