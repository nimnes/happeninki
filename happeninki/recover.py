"""Upload a runner's validated recovery database without sending any messages."""
import argparse
import os

from .http import HttpClient
from .releases import ReleaseState
from .store import Store, validate_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    validate_database(args.database)
    remote = ReleaseState(HttpClient(), os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY"))
    remote.release = remote.find_release()
    store = Store(args.database)
    try:
        remote.checkpoint(store)
        remote.prune()
    finally:
        store.close()
    print("Recovery database uploaded. No Telegram messages were sent.")


if __name__ == "__main__":
    main()
