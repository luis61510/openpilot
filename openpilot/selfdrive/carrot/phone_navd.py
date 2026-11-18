"""Managed entry point for the Carrot Navi v2 phone receiver."""

from openpilot.selfdrive.carrot.carrot_navi import main


if __name__ == "__main__":
  # Stage B adds SunnyPilot-specific Cereal services; use the receiver's
  # normal publisher startup instead of the Stage A --no-cereal mode.
  main()
