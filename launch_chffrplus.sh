#!/usr/bin/env bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"

source "$DIR/launch_env.sh"

# One-time rollback protection for the first boot of the four-feature test branch.
ROLLBACK_MARKER="/data/safe_staging/auto_rollback_pending"
ROLLBACK_BACKUP="/data/safe_staging/old_openpilot"
ROLLBACK_SOURCE_BRANCH="dev-sp-1015-opview"
ROLLBACK_SOURCE_COMMIT="a1b0ddf3fe683319773b927e9e7469162a431744"
ROLLBACK_TEST_BRANCH="dev-sp-1015-master-4features-autorevert"
ROLLBACK_BOOT_SECONDS=180

function restore_known_good {
  if [ ! -f "$ROLLBACK_MARKER" ]; then
    return 1
  fi

  echo "Automatic rollback requested: restoring $ROLLBACK_SOURCE_BRANCH"
  if [ ! -d "$ROLLBACK_BACKUP/.git" ]; then
    echo "Rollback backup is missing; refusing to replace the current installation"
    return 1
  fi

  BACKUP_BRANCH="$(git -C "$ROLLBACK_BACKUP" rev-parse --abbrev-ref HEAD 2>/dev/null)"
  BACKUP_COMMIT="$(git -C "$ROLLBACK_BACKUP" rev-parse HEAD 2>/dev/null)"
  if [ "$BACKUP_BRANCH" != "$ROLLBACK_SOURCE_BRANCH" ] || [ "$BACKUP_COMMIT" != "$ROLLBACK_SOURCE_COMMIT" ]; then
    echo "Rollback backup identity mismatch ($BACKUP_BRANCH / $BACKUP_COMMIT); refusing unsafe restore"
    return 1
  fi

  FAILED_DIR="/data/safe_staging/failed_openpilot_$(date +%s)"
  if ! mv "$DIR" "$FAILED_DIR"; then
    echo "Could not move the failed test installation"
    return 1
  fi
  if ! mv "$ROLLBACK_BACKUP" "$DIR"; then
    echo "Could not restore the known-good installation; putting the test tree back"
    mv "$FAILED_DIR" "$DIR"
    return 1
  fi

  rm -f "$ROLLBACK_MARKER"
  unset AUTO_ROLLBACK_PENDING
  cd "$DIR" || return 1
  echo "Rollback restored $ROLLBACK_SOURCE_BRANCH at $ROLLBACK_SOURCE_COMMIT"
  exec "$DIR/launch_chffrplus.sh"
}

function agnos_init {
  # TODO: move this to agnos
  sudo rm -f /data/etc/NetworkManager/system-connections/*.nmmeta
  rm -f /data/scons_cache/config.lock

  # set success flag for current boot slot
  sudo abctl --set_success

  # TODO: do this without udev in AGNOS
  # udev does this, but sometimes we startup faster
  sudo chgrp gpu /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0
  sudo chmod 660 /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0

  # Check if AGNOS update is required
  if [ "$(< /VERSION)" != "$AGNOS_VERSION" ]; then
    AGNOS_PY="$DIR/openpilot/common/hardware/comma/agnos.py"
    MANIFEST="$DIR/$AGNOS_MANIFEST_FILE"
    if "$AGNOS_PY" --verify "$MANIFEST"; then
      sudo reboot
    fi
    while true; do
      "$DIR/openpilot/common/hardware/comma/updater" "$AGNOS_PY" "$MANIFEST"
    done
  fi
}

function launch {
  # Remove orphaned git lock if it exists on boot
  [ -f "$DIR/.git/index.lock" ] && rm -f "$DIR/.git/index.lock"

  # Check to see if there's a valid overlay-based update available. Conditions
  # are as follows:
  # 1. The DIR init file must be older than the git repo (no local modifications).
  # 2. The finalized overlay must have been synced successfully.
  if [ -f "${DIR}/.overlay_init" ]; then
    find "${DIR}/.git" -newer "${DIR}/.overlay_init" | grep -q '.' 2> /dev/null
    if [ $? -eq 0 ]; then
      echo "${DIR} has been modified, skipping overlay update installation"
    else
      if [ -f "${STAGING_ROOT}/finalized/.overlay_consistent" ]; then
        if [ ! -d "$ROLLBACK_BACKUP" ]; then
          echo "Valid overlay update found, installing"
          LAUNCHER_LOCATION="${BASH_SOURCE[0]}"
          CURRENT_BRANCH="$(git -C "$DIR" rev-parse --abbrev-ref HEAD 2>/dev/null)"
          CURRENT_COMMIT="$(git -C "$DIR" rev-parse HEAD 2>/dev/null)"
          NEW_BRANCH="$(git -C "${STAGING_ROOT}/finalized" rev-parse --abbrev-ref HEAD 2>/dev/null)"

          mv "$DIR" "$ROLLBACK_BACKUP" || return 1
          if ! mv "${STAGING_ROOT}/finalized" "$DIR"; then
            mv "$ROLLBACK_BACKUP" "$DIR"
            echo "Could not activate finalized update; restored previous tree"
            return 1
          fi

          # Arm rollback only for the requested opview -> four-feature test upgrade.
          if [ "$CURRENT_BRANCH" = "$ROLLBACK_SOURCE_BRANCH" ] && [ "$CURRENT_COMMIT" = "$ROLLBACK_SOURCE_COMMIT" ] && [ "$NEW_BRANCH" = "$ROLLBACK_TEST_BRANCH" ]; then
            mkdir -p /data/safe_staging
            printf '%s\n' "$ROLLBACK_SOURCE_BRANCH" "$ROLLBACK_SOURCE_COMMIT" "$ROLLBACK_TEST_BRANCH" > "$ROLLBACK_MARKER"
            sync
            echo "Automatic rollback armed for first boot of $ROLLBACK_TEST_BRANCH"
          fi

          cd "$DIR" || return 1
          echo "Restarting launch script $LAUNCHER_LOCATION"
          unset AGNOS_VERSION
          exec "$DIR/launch_chffrplus.sh"
        else
          echo "openpilot backup found, not updating"
        fi
      fi
    fi
  fi

  # A pending marker means this is the first boot of the test installation.
  if [ -f "$ROLLBACK_MARKER" ]; then
    export AUTO_ROLLBACK_PENDING=1
    echo "Automatic rollback protection active (180-second startup window)"
  fi

  # handle pythonpath
  ln -sfn "$(pwd)" /data/pythonpath
  export PYTHONPATH="$PWD"

  # submodule package symlinks for PYTHONPATH imports on device.
  ln -sfn msgq_repo/msgq msgq
  ln -sfn opendbc_repo/opendbc opendbc
  ln -sfn rednose_repo/rednose rednose
  ln -sfn teleoprtc_repo/teleoprtc teleoprtc
  ln -sfn tinygrad_repo/tinygrad tinygrad

  # hardware specific init
  if [ -f /AGNOS ]; then
    agnos_init
  fi

  # write tmux scrollback to a file
  tmux capture-pane -pq -S-1000 > /tmp/launch_log

  # build before manager startup; on failure restore the known-good tree.
  cd "$DIR/openpilot/system/manager" || return 1
  if [ ! -f "$DIR/prebuilt" ]; then
    ./build.py
    BUILD_STATUS=$?
    if [ "$BUILD_STATUS" -ne 0 ] && [ -f "$ROLLBACK_MARKER" ]; then
      echo "Build failed during protected test boot; rolling back"
      restore_known_good
    elif [ "$BUILD_STATUS" -ne 0 ]; then
      echo "Build failed; preserving existing non-test recovery behavior"
      while true; do sleep 1; done
    fi
  fi

  if [ -f "$ROLLBACK_MARKER" ]; then
    # Do not let startup error dialogs block automatic recovery.
    export AUTO_ROLLBACK_PENDING=1
    ./manager.py &
    MANAGER_PID=$!

    for ((elapsed=0; elapsed<ROLLBACK_BOOT_SECONDS; elapsed++)); do
      MANAGER_STATE="$(ps -o stat= -p "$MANAGER_PID" 2>/dev/null | tr -d ' ')"
      if [ -z "$MANAGER_STATE" ] || [[ "$MANAGER_STATE" == Z* ]]; then
        wait "$MANAGER_PID"
        echo "Manager exited before startup health window; rolling back"
        restore_known_good
        break
      fi
      sleep 1
    done

    MANAGER_STATE="$(ps -o stat= -p "$MANAGER_PID" 2>/dev/null | tr -d ' ')"
    if [ -n "$MANAGER_STATE" ] && [[ "$MANAGER_STATE" != Z* ]]; then
      echo "Manager remained alive for $ROLLBACK_BOOT_SECONDS seconds; test boot accepted"
      rm -f "$ROLLBACK_MARKER"
      # Keep the previous tree as a named recovery copy without blocking future updates.
      if [ -d "$ROLLBACK_BACKUP" ]; then
        mv "$ROLLBACK_BACKUP" "/data/safe_staging/last_known_good_opview_$(date +%s)"
      fi
      wait "$MANAGER_PID"
    fi
  else
    ./manager.py
  fi

  # if broken, keep on screen error
  while true; do sleep 1; done
}

launch
