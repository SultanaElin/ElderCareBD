import argparse
import json

from daily_observation_migration import migrate_daily_observations


def main():
    parser = argparse.ArgumentParser(
        description="Add the Task 18A1 patient daily-observation table."
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--backup", required=True)
    args = parser.parse_args()
    result = migrate_daily_observations(args.database, args.backup)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
