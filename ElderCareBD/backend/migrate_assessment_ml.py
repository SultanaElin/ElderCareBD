import argparse
import json

from assessment_ml_migration import migrate_assessment_ml


def main():
    parser = argparse.ArgumentParser(
        description="Add nullable Task 14 assessment ML provenance columns."
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--backup", required=True)
    args = parser.parse_args()
    result = migrate_assessment_ml(args.database, args.backup)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
