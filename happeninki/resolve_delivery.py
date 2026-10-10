"""Resolve a held delivery after checking the Telegram channel manually."""
import argparse
import os

from .http import HttpClient
from .releases import ReleaseState
from .store import Store, validate_database
from .telegram import channel_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_key', help='Source identity from the delivery_holds report')
    parser.add_argument('--language', choices=('ru', 'en'), required=True)
    parser.add_argument('--database', default='data/events.db')
    parser.add_argument('--release-state', action='store_true')
    resolution = parser.add_mutually_exclusive_group(required=True)
    resolution.add_argument('--message-id', type=int, help='Existing Telegram message ID confirmed in the channel')
    resolution.add_argument('--retry', action='store_true', help='Confirm that no message was posted and permit a later retry')
    parser.add_argument('--message-kind', choices=('text', 'photo'), default='text')
    args = parser.parse_args()
    if args.message_id is not None and args.message_id <= 0:
        parser.error('--message-id must be positive')
    channel = os.getenv(f'TELEGRAM_CHANNEL_{args.language.upper()}', '').strip()
    if not channel:
        parser.error('Set the corresponding TELEGRAM_CHANNEL environment variable')
    remote = ReleaseState(HttpClient(), os.getenv('GITHUB_TOKEN'), os.getenv('GITHUB_REPOSITORY')) if args.release_state else None
    if remote:
        remote.restore(args.database)
    validate_database(args.database)
    store = Store(args.database)
    try:
        if args.source_key.startswith('digest:'):
            store.resolve_weekly_digest(args.source_key.removeprefix('digest:'), args.language, channel_hash(channel), args.message_id)
        else:
            store.resolve_delivery(args.source_key, args.language, channel_hash(channel), args.message_id, args.message_kind)
        if remote:
            remote.checkpoint(store)
    finally:
        store.close()
    print('Delivery resolved. No Telegram messages were sent.')


if __name__ == '__main__':
    main()
