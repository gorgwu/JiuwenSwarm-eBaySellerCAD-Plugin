"""Normalize eBay error details without exposing request credentials."""

import json
import socket
import ssl
import urllib.error
import xml.etree.ElementTree as ET


class InvalidResponseError(Exception):
    """The remote response could not be interpreted as the expected eBay response."""


def local_failure(exc, *, writes=False):
    """Classify observable failures without exposing exception text or credentials."""
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, (TimeoutError, socket.timeout)):
        code, category = 'CONNECTION_TIMEOUT', 'connection'
        message = 'The request timed out. Check your connection or try again later.'
    elif isinstance(reason, socket.gaierror):
        code, category = 'DNS_FAILURE', 'connection'
        message = 'The eBay address could not be resolved. Check DNS and your network connection.'
    elif isinstance(reason, ssl.SSLError):
        code, category = 'TLS_FAILURE', 'connection'
        message = 'A secure connection could not be established. Check your network and system certificates.'
    elif isinstance(exc, urllib.error.URLError) or isinstance(reason, ConnectionError):
        code, category = 'CONNECTION_FAILURE', 'connection'
        message = 'The request could not connect to the service. Check your network or try again later.'
    elif isinstance(exc, (InvalidResponseError, ET.ParseError)):
        code, category = 'INVALID_RESPONSE', 'response'
        message = 'The service returned a response the plugin could not read.'
    elif isinstance(exc, OSError):
        code, category = 'SYSTEM_IO_FAILURE', 'system'
        message = 'A local or network input/output error occurred. Check file access and your connection.'
    else:
        code, category = 'PLUGIN_FAILURE', 'internal'
        message = 'The plugin encountered an unexpected error.'
    if writes:
        message += ' The change may have been applied; check eBay before retrying.'
    return {'success': False, 'error': message, 'errors': [{'code': None, 'plugin_code': code,
            'message': message, 'category': category, 'domain': 'plugin'}]}


def ebay_errors(entries):
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return []
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        code = entry.get('errorId', entry.get('ErrorCode'))
        message = entry.get('longMessage') or entry.get('LongMessage') or entry.get('message') or entry.get('ShortMessage')
        details = {key: entry[key] for key in ('errorId', 'domain', 'category', 'message', 'longMessage') if key in entry}
        details.update({'code': code, 'message': message or 'eBay did not provide an explanation.',
                        'category': entry.get('category', entry.get('SeverityCode')),
                        'domain': entry.get('domain')})
        result.append(details)
    return result


def http_error(exc):
    raw = exc.read()
    errors = []
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            errors = ebay_errors(payload.get('errors', []))
            if not errors and payload.get('error'):
                errors = [{'code': payload['error'], 'message': payload.get('error_description') or 'eBay did not provide an explanation.', 'category': None, 'domain': 'oauth'}]
    except (ValueError, TypeError):
        try:
            root = ET.fromstring(raw)
            entries = []
            for node in root.iter():
                if node.tag.split('}')[-1] == 'Errors':
                    entries.append({child.tag.split('}')[-1]: child.text for child in node})
            errors = ebay_errors(entries)
        except (ET.ParseError, ValueError):
            pass
    if not errors:
        errors = [{'code': None, 'message': 'eBay did not provide a readable error explanation.', 'category': None, 'domain': None}]
    return {'success': False, 'http_status': exc.code, 'errors': errors}


def trading_failure(response):
    errors = ebay_errors(response.get('Errors', []))
    if not errors:
        errors = [{'code': None, 'message': 'eBay reported a failure without an error explanation.', 'category': None, 'domain': None}]
    return errors
