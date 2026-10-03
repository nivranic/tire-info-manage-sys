"""Explicit local identity migration; never fetch or parse source pages."""
import json
import sys

from tire_api.identity_contract import IdentityContractError, main


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except IdentityContractError as error:
        print(json.dumps({'error_code': error.code}))
        raise SystemExit(2) from None
    except (OSError, ValueError):
        print(json.dumps({'error_code': 'invalid_local_request'}))
        raise SystemExit(2) from None
