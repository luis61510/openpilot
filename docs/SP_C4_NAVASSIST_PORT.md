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

### Gaps identified in the C4 static audit

- [ ] Port the source branch's pairing/reset controls and navigation/lane HUD
      into the release-mici C4 UI paths; current target UI files are unchanged.
- [ ] Decide and implement equivalent NavAssist control integration for the
      stock model runner, or explicitly require a compatible tinygrad bundle.
- [ ] Run the imported UI contract tests after the UI port; current test
      expectations refer to source-branch paths and C3XL-era assumptions.

- [x] Branch created from the official SunnyPilot release-mici commit.
- [x] Four-layer source modules copied selectively.
- [x] C4 camera service/stream/intrinsics adapted in lane_topologyd.
- [x] Manager process gates target C4 `mici` and Tesla onroad operation.
- [x] Cereal schema/service/Params source definitions added.
- [x] Non-Tesla modeld DesireHelper path isolated.
- [ ] Run Python syntax/compile checks on all imported modules.
- [ ] Regenerate Cap'n Proto C++ artifacts with the target build toolchain.
- [ ] Verify service registry generation against `cereal/services.py`.
- [ ] Run imported NavAssist, lane-topology and control-gate unit tests.
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
