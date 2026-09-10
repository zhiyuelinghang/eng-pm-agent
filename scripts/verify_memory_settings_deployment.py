"""Verify the live six-setting contract without changing saved configuration."""
from pathlib import Path
import json
import os

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {'learning_enabled', 'learning_model_config', 'learning_interactions_enabled',
          'learning_business_events_enabled', 'group_learning_enabled', 'compression_model_config'}


def main():
    load_dotenv(ROOT / '.env')
    with httpx.Client(base_url='http://127.0.0.1:25173/agentscope-api', timeout=30) as client:
        client.headers['Authorization'] = 'Bearer ' + os.environ['AGENTSCOPE_SERVICE_TOKEN']
        assert client.get('/agent/platform/memory-settings').status_code == 403
        login = client.post('/auth/login', json={'username': os.environ['AGENTSCOPE_ADMIN_USERNAME'],
            'password': os.environ['AGENTSCOPE_ADMIN_PASSWORD']})
        login.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + login.json()['access_token']
        result = client.get('/agent/platform/memory-settings')
        result.raise_for_status()
        data = result.json()
        assert set(data['settings']) == FIELDS
        legacy = client.put('/agent/platform/memory-settings', json={
            'settings': {**data['settings'], 'memory_profile_enabled': True},
            'expected_revision': data['revision']})
        assert legacy.status_code == 422
        missing_revision = client.put('/agent/platform/memory-settings', json={'settings': data['settings']})
        assert missing_revision.status_code == 422
        reset = client.post('/agent/platform/memory-settings/reset')
        assert reset.status_code in (404, 405)
        after = client.get('/agent/platform/memory-settings').json()
        assert after['settings'] == data['settings'] and after['revision'] == data['revision']
        agents = client.get('/agent/').json()['agents']
        for agent in agents:
            assert not {'memory_policy', 'memory_read_scopes', 'memory_write_scopes'} & agent['data']['platform_config'].keys()
    report = {'status': 'passed', 'configuration_unchanged': True, 'fields': sorted(FIELDS),
        'revision': data['revision'], 'learning_model': data['settings']['learning_model_config']['model'],
        'compression_model': data['settings']['compression_model_config']['model'],
        'legacy_fields_rejected': legacy.status_code, 'missing_revision_rejected': missing_revision.status_code,
        'reset_removed': reset.status_code, 'agents_without_memory_controls': len(agents)}
    (ROOT / 'artifacts/memory-settings-live-api-verification.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
