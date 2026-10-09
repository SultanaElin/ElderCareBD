import argparse
import json

from prescription_foundation_migration import migrate_prescription_foundation


def main():
    parser = argparse.ArgumentParser(
        description="Add the secure prescription and medicine foundation schema."
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--backup", required=True)
    args = parser.parse_args()
    result = migrate_prescription_foundation(args.database, args.backup)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
