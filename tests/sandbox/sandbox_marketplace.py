"""Resolve the marketplace used by the Sandbox test scripts."""
from common.oauth import load_settings


def test_marketplace(override=None):
    value = (override if override is not None else load_settings().get('EBAY_MARKETPLACE_ID', 'EBAY_CA')).strip().upper()
    if value != 'EBAY_CA':
        raise ValueError('Sandbox tests support EBAY_CA only; set EBAY_MARKETPLACE_ID accordingly.')
    return value
