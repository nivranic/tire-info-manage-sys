"""Public parser identity and service-side binding; no executable paths in evidence."""
from copy import deepcopy


def parser_identity(selection):
    if not isinstance(selection, dict):
        return None
    value = {key: selection.get(key) for key in ('bundle_id', 'parser_digest', 'deployment_revision')}
    if (any(not isinstance(value[key], str) or len(value[key]) != 64
            or any(char not in '0123456789abcdef' for char in value[key])
            for key in ('bundle_id', 'parser_digest'))
            or type(value['deployment_revision']) is not int or value['deployment_revision'] < 1):
        return None
    return value


def verified_observation_recorder(recorder, selection):
    expected = parser_identity(selection)

    def record(observation):
        from .captures import CaptureWriteError
        if (expected is None or observation.get('parser_identity') != expected
                or observation.get('parser_version') != selection['parser_version']):
            raise CaptureWriteError('parser_identity_mismatch')
        recorder(observation)

    return record


def check_result_identity(selection, result):
    from .parser_releases import ParserDeploymentError
    if (parser_identity(selection) is None or result.get('parser_identity') != parser_identity(selection)
            or result.get('parser_version') != selection['parser_version']):
        raise ParserDeploymentError('parser_identity_mismatch')


def execution_outcome(result):
    receipt = result.get('parser_receipt')
    return {'state': 'not_modified' if result.get('status') == 'not_modified' else
                    'completed' if result.get('status') == 'ok' else
                    'failed' if receipt else 'not_started',
            'receipt': deepcopy(receipt) if isinstance(receipt, dict) else {},
            'error_code': result.get('parser_error') or result.get('reason')}
