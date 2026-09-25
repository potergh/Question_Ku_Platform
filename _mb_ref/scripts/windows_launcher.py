"""Compatibility entry point for the Windows BAT launcher."""
from scripts.local_launcher import main

if __name__ == "__main__":
    raise SystemExit(main())
