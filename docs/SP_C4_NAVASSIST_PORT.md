# SP C4 NavAssist port status

## Source and target

- Target repository: `luis61510/openpilot`
- Target branch: `sp-c4-navassit`
- Base: `sunnypilot/sunnypilot:release-mici`
- Base commit: `6a17f75c6bcb67c85f252a1acc342d94d5b8a4d2`
- Feature source: `Sniper-Eon/openpilot:navassist-jetlink-tesla`
- Source commit: `3cb5402233be38c742982f6f1063bd242b5f9a01`

This is a selective feature port, not a merge of the Sniper branch history.
The official release-mici codebase remains the base.

## Implemented in the branch

- NavAssist phone ingress, v3 protocol, identity/pairing, discovery, UDP
  receiver, HTTP server, settings, publisher and navigation state.
- Lane topology geometry, metric marking, tracker, primary model and UI bridge.
- Navigation lane intent, turn signal coordination and lane topology publisher.
- Tesla OEM lane feedback decoder and OEM lane-change gate.
- Lane boundary blocker, road-edge controller, relative lane consistency,
  turn-entry and turn-completion helpers.
- Cereal definitions for `NavAssistStateSP`, `LaneTopologyStateSP` and
  `NavLaneIntentSP`, plus `ModelDataV2SP` edge/turn diagnostics fields.
- Cereal event/service registrations and NavAssist pairing Params.
- Manager process registration with a C4 `mici` hardware gate and Tesla/onroad
  gates for the control-facing observers.
- C4 camera adaptation in `lane_topologyd`.
- Tesla modeld integration with visual boundary, OEM, blind-spot, turn-entry
  and DesireHelper gates.
- Non-Tesla modeld path retains a copy of the release-mici DesireHelper.
- Source lane-topology, NavAssist and control-gate test files have been imported.

## Explicitly disabled or not connected

- ARS408 efficiency overtaking: disabled because the target does not yet have
  a validated equivalent of Sniper's `radarTracks` contract.
- Navigation speed ceiling: the speed controller module is present, but it is
  not connected to the release-mici longitudinal planner.
- Standalone diagnostics recorder: not registered or started.
- OEM CAN compatibility: the imported decoder expects bus 1 and addresses
  `0x239` / `0x399`; this mapping has not been confirmed on a C4 Tesla.

## Validation checklist

### Source/static checks

### Cereal / Cap'n Proto: C4 runtime audit (2026-11-14)

- [x] The three new message structs reuse the original SunnyPilot reserved struct IDs:
      `CustomReserved11` → `NavAssistStateSP`,
      `CustomReserved12` → `LaneTopologyStateSP`,
      `CustomReserved13` → `NavLaneIntentSP`.
- [x] Event fields reuse reserved ordinals 137–139; existing Event ordinals
      and types were not rewritten.
- [x] No duplicate struct IDs or Event field ordinals were found in the added
      schema range.
- [x] `services.py` and checked-in `services.h` have matching service names
      and settings (83 entries each).
- [x] Confirmed the actual `release-mici` Python runtime dependency contract:
      `pycapnp==2.1.0`; the C++ compiler package is the vendored
      `capnproto==1.0.1` from `commaai/dependencies:release-capnproto`.
      The `CAPNP_VERSION == 1000001` marker in generated C++ headers is
      consistent with Cap'n Proto 1.0.1.
- [x] Confirmed the `release-mici` install branch does not contain a
      top-level `SConstruct`; the normal source-tree SCons build cannot be
      invoked from this release branch as if it were a development checkout.
      The C4 runtime path loads `cereal/*.capnp` through Python pycapnp.
- [x] Added `cereal/messaging/tests/test_c4_runtime_schema.py` to check the
      C4 `pycapnp==2.1.0` dependency, the physical `mici` identity when on
      comma hardware, the three Event union fields, service registrations,
      custom struct fields, ModelDataV2SP diagnostics fields, and serialization
      round-trips using the runtime Python Cereal API.
- [x] Added `tools/rebuild_cereal_c4.sh`, which refuses a compiler version
      other than Cap'n Proto 1.0.1, regenerates both `cereal/gen/cpp` and
      `openpilot/cereal/gen/cpp`, and synchronizes both generated service
      registries from `cereal/services.py`.
- [ ] Run the new smoke test in the actual C4 Python environment:
      `python3 -m cereal.messaging.tests.test_c4_runtime_schema`.
      It has not yet been executed on the device.
- [ ] When a native C++ rebuild is required, run
      `bash tools/rebuild_cereal_c4.sh` from the repository root in the
      release-mici Python environment. The updated helper has not yet been
      executed; neither shell validation nor compiler invocation is claimed.
- [ ] The checked-in C++ generated files in both `cereal/gen/cpp` and
      `openpilot/cereal/gen/cpp` remain stale relative to the updated schemas.
      This does not prevent the Python pycapnp runtime smoke test from loading
      the schema, but it remains a blocker for a native C++ rebuild or C++
      consumer that needs the new NavAssist types. Regenerate both copies with
      the C4-matched Cap'n Proto 1.0.1 compiler before such a build.
- [ ] No C++ compile or native binary rebuild has been performed. The release
      branch lacks the top-level build graph, and no C4 device build session
      was available in this review.

### Gaps identified in the C4 static audit

- [x] Add NavAssist phone-pairing status and a confirmed, offroad-only
      pairing-reset action to the C4 Mici developer settings.
- [ ] Port the source branch's lane-topology/navigation HUD into the C4
      onroad UI; this remains a visible UI gap.
- [x] Add equivalent Tesla NavAssist control integration to the stock model
      runner; non-Tesla vehicles retain the preserved legacy DesireHelper path.
      Runtime behavior still requires C4 validation.
- [x] Add NavAssist phone-pairing status and a confirmed pairing-reset
      action to the C4 Mici developer settings.
- [ ] Port the source branch's lane-topology/navigation HUD into the C4
      onroad UI; this remains a visible UI gap.

- [x] Branch created from the official SunnyPilot release-mici commit.
- [x] Four-layer source modules copied selectively.
- [x] C4 camera service/stream/intrinsics adapted in lane_topologyd.
- [x] Manager process gates target C4 `mici` and Tesla onroad operation.
- [x] Cereal schema/service/Params source definitions added.
- [x] Non-Tesla modeld DesireHelper path isolated.
- [ ] Run Python syntax/compile checks on all imported modules.
- [ ] Regenerate Cap'n Proto C++ artifacts with `bash tools/rebuild_cereal_c4.sh` before any native C++ rebuild.
- [x] Synchronize `cereal/services.h` and the packaged
      `openpilot/cereal/services.h` with all three NavAssist services.
- [ ] Execute the regeneration helper and verify its generated outputs on C4.
- [ ] Run the C4 Cereal runtime smoke test, then imported NavAssist, lane-topology and control-gate unit tests.
- [ ] Resolve any test failures caused by source/target API differences.

### C4 hardware checks

- [ ] Install only after the build and static checks pass.
- [ ] Confirm C4 device type reports `mici` and all three processes start.
- [ ] Confirm `VISION_STREAM_ROAD`, `roadCameraState` and `liveCalibration`
      remain fresh on C4.
- [ ] Confirm laneTopologyStateSP timestamps and validForControl behavior.
- [ ] Capture C4 Tesla CAN and confirm bus, address, DLC, counter, checksum,
      timestamps and signal semantics for 0x239/0x399.
- [ ] Replay CAN captures and verify loss/stale/malformed packets fail closed.
- [ ] Verify blind-spot and driver-override vetoes independently.
- [ ] Closed-course validation of turn signal, lane intent, boundary blocking,
      turn entry and turn completion.
- [ ] Verify non-Tesla behavior is unchanged.

## Operational safety

A successful code import or static review is not evidence of a successful
Comma 4 build or vehicle test. Do not enable automatic lane changes on public
roads before all C4 camera/CAN, build, startup and closed-course gates above
have passed. Missing or stale sensor/CAN data must never be interpreted as
permission.
