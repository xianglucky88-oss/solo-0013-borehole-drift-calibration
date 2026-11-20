import argparse
import json
from pathlib import Path
import sqlite3

from .archive import publish, read_profile


def main():
    parser = argparse.ArgumentParser(description='Publish calibrated borehole temperature profiles')
    parser.add_argument('--db', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('publish').add_argument('source', type=Path)
    read = commands.add_parser('read')
    read.add_argument('borehole')
    read.add_argument('version')
    args = parser.parse_args()
    try:
        if args.command == 'publish':
            result = publish(args.db, json.loads(args.source.read_text(encoding='utf-8')))
        else:
            result = read_profile(args.db, args.borehole, args.version)
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        parser.exit(2, f'error: {error}\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
