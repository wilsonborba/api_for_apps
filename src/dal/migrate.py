"""DAL-owned Alembic command entry point.

Run from the repository root, for example:
    python -m src.dal.migrate upgrade head
"""
from pathlib import Path
import sys

from alembic.config import main


if __name__ == "__main__":
    config_path = Path(__file__).with_name("alembic.ini")
    main(argv=["-c", str(config_path), *sys.argv[1:]])
