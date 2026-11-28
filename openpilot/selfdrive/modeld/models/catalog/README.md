# Official driving model catalog snapshot

Synced from the official sunnypilot model catalog on 2026-11-28.

- Qualcomm catalog: `driving_models_v25.json` — 81 bundles.
- Chestnut catalog: `driving_models_chestnut_v28.json` — 25 bundles.
- Both catalogs require selector version 21.
- Source repository: https://github.com/sunnypilot/sunnypilot-models/tree/gh-pages/docs
- Source blob SHA (Qualcomm): `a63f8ffcd92306ecd1ae540768e1512ab3908045`
- Source blob SHA (Chestnut): `c6c5e85a4e0b641ec79f1023cea3873d83ca32e4`

## Important integration note

These files are an exact catalog snapshot only. The current `dev-sp-1015` base does not contain the official runtime model-management stack (`openpilot/sunnypilot/models`), the model-selector UI, or the associated `ModelManagerSP` cereal schema. Therefore these JSON files are **not yet consumed by the running C4 model selector**. Do not treat this snapshot alone as enabling model switching.

The next integration step is to port and adapt the official model manager, schema, UI, download/cache/verification paths, and modeld runner handoff as a coordinated change, then test both Qualcomm and Chestnut paths before deploying to C4.
