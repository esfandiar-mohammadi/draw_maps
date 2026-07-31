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

Reproduce with `tools/foundry_test_env.sh` (needs Foundry credentials in
`~/.foundry_test.json`) and `tools/foundry_ui_drive.py`. See README §C.6.
