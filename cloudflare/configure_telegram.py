"""Configure Telegram after deployment; prompts never echo the bot token."""
import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from happeninki.http import HttpClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True, help='HTTPS Worker origin')
    parser.add_argument('--replace-webhook', action='store_true', help='Explicitly replace a webhook hosted elsewhere')
    parser.add_argument('--secrets-file', type=Path, help='Ignored local JSON credential file')
    args = parser.parse_args()
    parts = urlsplit(args.url)
    if parts.scheme != 'https' or not parts.netloc or parts.username or parts.path not in {'', '/'} or parts.query or parts.fragment:
        parser.error('--url must be an HTTPS origin')
    credentials = json.loads(args.secrets_file.read_text()) if args.secrets_file else {}
    token = credentials.get('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN') or getpass.getpass('Telegram bot token (hidden): ')
    secret = credentials.get('TELEGRAM_WEBHOOK_SECRET') or os.getenv('TELEGRAM_WEBHOOK_SECRET') or getpass.getpass('Webhook secret, identical to Worker secret (hidden): ')
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
        parser.error('Provide the existing Telegram bot token')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', secret):
        parser.error('Webhook secret must contain only letters, digits, underscores or hyphens')
    http = HttpClient()
    readiness = http.request(args.url.rstrip('/') + '/health', service='Favourites setup', retry=False)
    if not isinstance(readiness, dict) or readiness.get('ok') is not True:
        raise RuntimeError('Worker is not ready; configure its secrets and D1 first')
    def api(method, payload=None):
        result = http.request(f'https://api.telegram.org/bot{token}/{method}',
            method='POST', body=payload or {}, service='Telegram setup', retry=False)
        if not result.get('ok'):
            raise RuntimeError('Telegram rejected setup')
        return result['result']
    bot = api('getMe')
    target = args.url.rstrip('/') + '/telegram'
    previous = api('getWebhookInfo')
    if previous.get('url') and previous['url'] != target and not args.replace_webhook:
        raise RuntimeError('This bot already uses another webhook. Review it before using --replace-webhook.')
    api('setWebhook', {'url': target, 'secret_token': secret, 'max_connections': 1,
                      'allowed_updates': ['message', 'callback_query'], 'drop_pending_updates': False})
    for language, descriptions in [('', ('My saved upcoming events', 'How to save events', 'Data storage and privacy', 'Delete my favourites')),
                                  ('en', ('My saved upcoming events', 'How to save events', 'Data storage and privacy', 'Delete my favourites')),
                                  ('ru', ('Мои предстоящие события', 'Как сохранять события', 'Хранение данных', 'Удалить избранное'))]:
        api('setMyCommands', {'language_code': language, 'scope': {'type': 'all_private_chats'},
            'commands': [{'command': command, 'description': description} for command, description in
                         zip(('events', 'help', 'privacy', 'delete_me'), descriptions)]})
    api('setChatMenuButton', {'menu_button': {'type': 'commands'}})
    info = api('getWebhookInfo')
    if info.get('url') != target:
        raise RuntimeError('Webhook verification failed')
    print(f"Configured @{bot['username']}. Webhook verified. No pending updates were discarded.")


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Do not expose HTTP URLs or credentials in a traceback.
        print(f'Setup failed: {error}', file=sys.stderr)
        sys.exit(1)
