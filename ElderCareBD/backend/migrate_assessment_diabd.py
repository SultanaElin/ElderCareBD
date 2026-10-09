import argparse
import json

from assessment_diabd_migration import migrate_assessment_diabd


def main():
    parser = argparse.ArgumentParser(
        description="Add nullable Task 14 DiaBD-v3 assessment provenance columns."
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--backup", required=True)
    args = parser.parse_args()
    result = migrate_assessment_diabd(args.database, args.backup)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
