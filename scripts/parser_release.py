"""Local trusted Parser operations; request files contain metadata, never code."""
import json
import sys
from tire_api.parser_releases import main


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except (OSError, ValueError):
        # Validation errors can include the rejected request; don't echo it.
        print(json.dumps({'error_code': 'invalid_local_request'}))
        raise SystemExit(2) from None
