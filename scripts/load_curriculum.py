"""Load the curriculum source tree into the database.

Usage:
    python scripts/load_curriculum.py [--publish] [--curriculum-dir PATH]

Re-running with unchanged source is a no-op. Modifying a published version's
source is rejected: bump `version` in `curriculum/framework.yml` instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.app.curriculum import (
    CurriculumError,
    ImmutableCurriculumError,
    load_curriculum,
)
from apps.api.app.db.session import session_scope
from apps.api.app.settings import settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load curriculum source into the database.")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="mark the loaded version as published (immutable from then on)",
    )
    parser.add_argument("--curriculum-dir", type=Path, default=settings.curriculum_dir)
    args = parser.parse_args(argv)

    try:
        with session_scope() as session:
            result = load_curriculum(session, args.curriculum_dir, publish=args.publish)
            action = "Created" if result.created else "Reused"
            print(
                f"{action} curriculum version {result.version.semantic_version} "
                f"({result.version.status.value}): {result.skill_nodes} skill nodes, "
                f"{result.objectives} objectives, {result.edges} prerequisite edges."
            )
    except CurriculumError as exc:
        print("Curriculum validation failed:", file=sys.stderr)
        for error in exc.errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    except ImmutableCurriculumError as exc:
        print(f"Refused to modify published curriculum: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
