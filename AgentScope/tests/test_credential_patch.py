"""Credential PATCH preserves omitted secrets, catalogues and shared-edit ACLs."""
from copy import deepcopy

from fastapi import FastAPI
import httpx
import pytest
import pytest_asyncio

from agentscope.app._router import _credential as routes
from agentscope.app._service import ResourceAccessService
from agentscope.app.access import ResourceKind, ResourcePermission, ResourceRef
from agentscope.app.storage import AsyncSQLAlchemyStorage
from agentscope.credential import CredentialModelDefinition, CustomOpenAICredential


class Shares:
    async def list_accessible(self, viewer_id, kind, storage):
        if kind != ResourceKind.CREDENTIAL or viewer_id not in {'editor', 'reader'}:
            return []
        return [ResourceRef(kind=kind, owner_id='owner', resource_id='test-credential',
            permission=ResourcePermission.EDIT if viewer_id == 'editor' else ResourcePermission.READ)]


@pytest_asyncio.fixture
async def environment(tmp_path):
    storage = AsyncSQLAlchemyStorage('sqlite+aiosqlite:///' + (tmp_path / 'credentials.db').as_posix())
    async with storage:
        credential = CustomOpenAICredential(id='test-credential', name='Original',
            api_key='fictional-test-key-original', base_url='https://example.invalid/v1')
        credential.model_catalog.manual_models = [CredentialModelDefinition(name='configured-model')]
        credential.model_catalog.discovered_models = [CredentialModelDefinition(name='discovered-model')]
        credential.model_catalog.hidden_model_ids = ['hidden-model']
        credential.model_catalog.model_default_parameters = {'configured-model': {'temperature': .2}}
        await storage.upsert_credential('owner', credential)
        access = ResourceAccessService(storage, Shares())
        app = FastAPI()
        app.include_router(routes.credential_router)
        app.dependency_overrides[routes.get_storage] = lambda: storage
        app.dependency_overrides[routes.get_resource_access_service] = lambda: access
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            yield app, client, storage, access


@pytest.mark.asyncio
@pytest.mark.parametrize('viewer', ['owner', 'editor'])
@pytest.mark.parametrize('changes', [
    {'name': 'Updated'},
    {'api_key': 'fictional-test-key-updated'},
    {'base_url': 'https://new.example.invalid/v1'},
    {'type': 'custom_openai_credential', 'name': 'Updated', 'api_key': 'fictional-test-key-updated',
        'base_url': 'https://new.example.invalid/v1'},
])
async def test_partial_update_preserves_all_unspecified_fields(environment, viewer, changes):
    app, client, storage, _access = environment
    app.dependency_overrides[routes.get_current_user_id] = lambda: viewer
    before = (await storage.get_credential('owner', 'test-credential')).data
    response = await client.patch('/credential/test-credential', json={'data': changes})
    assert response.status_code == 200, response.text
    after = (await storage.get_credential('owner', 'test-credential')).data
    assert after == {**before, **changes}
    assert after['model_catalog'] == before['model_catalog']
    if viewer == 'editor':
        assert await storage.get_credential(viewer, 'test-credential') is None
        assert response.json()['data'] == {'type': 'custom_openai_credential', 'name': after['name']}
        assert 'fictional-test-key' not in response.text
    else:
        assert response.json()['data']['name'] == after['name']


@pytest.mark.asyncio
@pytest.mark.parametrize('viewer,status', [('reader', 403), ('unrelated', 404)])
async def test_existing_access_policy_prevents_unauthorized_edits(environment, viewer, status):
    app, client, storage, _access = environment
    app.dependency_overrides[routes.get_current_user_id] = lambda: viewer
    before = (await storage.get_credential('owner', 'test-credential')).data
    response = await client.patch('/credential/test-credential', json={'data': {'name': 'Not permitted'}})
    assert response.status_code == status
    assert (await storage.get_credential('owner', 'test-credential')).data == before


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'model_catalog': {}}, {'type': 'deepseek_credential'}, {'id': 'different'},
    {'unsupported_provider_field': 'value'}, {'api_key': None}, {'base_url': 'invalid-url'},
])
async def test_unsupported_or_invalid_patch_cannot_change_provider_catalog_or_data(environment, changes):
    app, client, storage, _access = environment
    app.dependency_overrides[routes.get_current_user_id] = lambda: 'owner'
    before = deepcopy((await storage.get_credential('owner', 'test-credential')).data)
    response = await client.patch('/credential/test-credential', json={'data': changes})
    assert response.status_code == 422, response.text
    assert (await storage.get_credential('owner', 'test-credential')).data == before
    assert 'fictional-test-key' not in response.text


@pytest.mark.asyncio
async def test_shared_editor_can_save_the_same_visible_name_type_payload(environment):
    app, client, storage, access = environment
    app.dependency_overrides[routes.get_current_user_id] = lambda: 'editor'
    visible = await access.get_resource('editor', ResourceKind.CREDENTIAL, 'test-credential')
    assert set(visible.data) == {'name', 'type'}
    response = await client.patch('/credential/test-credential', json={'data': {**visible.data, 'name': 'Shared edit'}})
    assert response.status_code == 200
    record = await storage.get_credential('owner', 'test-credential')
    assert record.data['api_key'] == 'fictional-test-key-original'
    assert record.data['base_url'] == 'https://example.invalid/v1'
    assert record.data['name'] == 'Shared edit'
