"""Persistent record of resources created by a single Sandbox test run."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path


def save(path: Path, journal: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    try:
        tmp.write_text(json.dumps(journal, indent=2) + '\n', encoding='utf-8')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def create(path: Path, seller_id: str) -> dict:
    if path.exists():
        raise ValueError('Journal already exists; choose another path.')
    if not seller_id.strip():
        raise ValueError('Sandbox seller ID is required.')
    journal = {'version': 1, 'environment': 'sandbox', 'run_id': uuid.uuid4().hex,
               'seller_id': seller_id, 'resources': [], 'unresolved': []}
    save(path, journal)
    return journal


def add(path: Path, journal: dict, kind: str, resource_id: str) -> None:
    allowed = {'offer', 'inventory_item', 'location', 'fulfillment_policy', 'payment_policy', 'return_policy', 'trading_listing'}
    if kind not in allowed or not isinstance(resource_id, str) or not resource_id.strip():
        raise ValueError('Invalid resource type or ID.')
    if any(r['kind'] == kind and r['id'] == resource_id for r in journal['resources']):
        raise ValueError('Resource already recorded.')
    journal['resources'].append({'kind': kind, 'id': resource_id, 'status': 'created'})
    save(path, journal)


def load(path: Path) -> dict:
    journal = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(journal, dict) or journal.get('version') != 1 or journal.get('environment') != 'sandbox':
        raise ValueError('Invalid Sandbox journal.')
    if not isinstance(journal.get('resources'), list) or not isinstance(journal.get('seller_id'), str):
        raise ValueError('Incomplete Sandbox journal.')
    return journal
