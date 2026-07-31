# Verification evidence

- `foundry-v14-docker-serve-module-install.png` — real Foundry **v14.365** running in
  a `felddy/foundryvtt` container whose user data is a **root-only named volume**,
  installing the module from the manifest URL served by `install.sh --serve-module`
  while the installer had **no Docker access** (stubbed to fail like a
  socket-permission denial). Foundry's console reported *"Module
  wall-annotation-companion was installed successfully"*.
- `foundry-v14-docker-module-listed.png` — the same instance listing **Wall
  Annotation Companion 2.2.0** under Add-on Modules afterwards. Ground truth inside
  the container: `/data/Data/modules/wall-annotation-companion`, owned by
  `node:node (1000:1000)` — Foundry's own user.

- `foundry-v14-walls-detected.png`, `foundry-v13-walls-detected.png`,
  `foundry-v12-walls-detected.png` — in-game detection on all three supported
  Foundry majors, each in its own real container: **198 walls** on the same
  1280×1280 map (1.9 s / 1.8 s / 1.5 s), walls layer active so the result is
  visible. v12 registers the toolbar button through the old `tools` **array**,
  v13/v14 through the `tools` **object**; both paths verified.

Reproduce with `tools/foundry_test_env.sh` (needs Foundry credentials in
`~/.foundry_test.json`) and `tools/foundry_ui_drive.py`. See README §C.6.
