"""Managed entry point for the Carrot Navi v2 phone receiver."""
import sys

from openpilot.selfdrive.carrot.carrot_navi import main


if __name__ == "__main__":
  # Stage A is transport-only. Cereal publication is deliberately disabled
  # until SunnyPilot-specific schemas and services are implemented.
  sys.argv = [sys.argv[0], "--no-cereal"]
  main()
