"""Native image input with local synthetic images and an in-memory business DB."""
import asyncio
import base64
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError
import pytest

from backend.tests.test_engineering_knowledge_conversations import db, _admin
from backend.app import agent_conversations_api as api
from backend.app import agent_image_attachments as images
from backend.app.agent_api_support import _initialization_attachment_manifest_context, _initialization_files_for_message
from backend.app.agentscope_client import AgentScopeReply
from backend.app.initialization_attachment_store import store_parsed_initialization_attachment, store_failed_initialization_attachment
from backend.app.models import AgentConversation, Project, ProjectInitializationFile
from backend.app.schemas import AgentConversationImageInput, AgentConversationMessageInput
from backend.app.system_attachment_parser import ParsedAttachment


def raw_image(fmt='PNG'):
    stream = BytesIO()
    Image.new('RGB', (2, 2), 'red').save(stream, format=fmt)
    return stream.getvalue()


def inline_image(fmt='PNG'):
    return AgentConversationImageInput(name='测试图片.'+fmt.lower(),
        media_type=images.NATIVE_IMAGE_TYPES[fmt], data=base64.b64encode(raw_image(fmt)).decode('ascii'))


@pytest.mark.parametrize('fmt', ['PNG','JPEG','WEBP','GIF'])
def test_supported_original_bytes_reach_native_data_block_without_ocr(fmt, tmp_path):
    supplied = inline_image(fmt)
    blocks, ids = images.image_blocks_for_turn([supplied], [], upload_dir=tmp_path)
    assert ids == set()
    assert blocks == [{'type':'data','name':supplied.name,'source':{
        'type':'base64','media_type':supplied.media_type,'data':supplied.data}}]


@pytest.mark.parametrize('value', ['not base64!', 'https://example.invalid/private.png', 'data:image/png;base64,AAAA'])
def test_url_path_and_invalid_base64_are_not_image_sources(value, tmp_path):
    supplied = inline_image().model_copy(update={'data':value})
    with pytest.raises(HTTPException) as denied:
        images.image_blocks_for_turn([supplied], [], upload_dir=tmp_path)
    assert denied.value.status_code == 422


@pytest.mark.parametrize('fmt,declared', [('PNG','image/jpeg'), ('TIFF','image/png')])
def test_real_format_must_match_supported_declared_type(fmt, declared, tmp_path):
    supplied = AgentConversationImageInput(name='image.png', media_type=declared,
        data=base64.b64encode(raw_image(fmt)).decode('ascii'))
    with pytest.raises(HTTPException) as denied:
        images.image_blocks_for_turn([supplied], [], upload_dir=tmp_path)
    assert denied.value.status_code == 422


def test_image_object_does_not_accept_urls_or_storage_paths():
    for extra in ({'url':'https://example.invalid'}, {'storage_path':'C:/private.png'}):
        with pytest.raises(ValidationError):
            AgentConversationImageInput(**{**inline_image().model_dump(), **extra})
    with pytest.raises(ValidationError):
        AgentConversationImageInput(name='diagram.svg', media_type='image/svg+xml', data='AAAA')


def test_corrupt_image_payload_is_a_validation_error(tmp_path):
    content = bytearray(raw_image())
    content[content.index(b'IDAT') + 5] ^= 255
    supplied = inline_image().model_copy(update={'data':base64.b64encode(content).decode('ascii')})
    with pytest.raises(HTTPException) as denied:
        images.image_blocks_for_turn([supplied], [], upload_dir=tmp_path)
    assert denied.value.status_code == 422


def test_count_and_combined_decoded_bytes_are_bounded(monkeypatch, tmp_path):
    with pytest.raises(ValidationError):
        AgentConversationMessageInput(content='看图', image_attachments=[inline_image()] * 9)
    monkeypatch.setattr(images, 'MAX_IMAGE_BYTES', len(raw_image()) * 2 - 1)
    with pytest.raises(HTTPException) as large:
        images.image_blocks_for_turn([inline_image(), inline_image()], [], upload_dir=tmp_path)
    assert large.value.status_code == 413


def setup_conversation(db, suffix='owner', kind='business'):
    user = _admin(db, suffix)
    project = Project(name='原生图片测试项目')
    db.add(project)
    db.flush()
    conversation = AgentConversation(project_id=project.id, user_id=user.id, agent_id='agent',
        agent_name='测试智能体', title='测试会话', conversation_type=kind, agentscope_session_id='session-'+suffix)
    db.add(conversation)
    db.commit()
    return user, project, conversation


def initial_file(db, tmp_path, conversation, user, *, name='已选图片.png', parsed=True):
    folder = tmp_path / 'project-initialization' / str(conversation.project_id) / str(conversation.id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(raw_image())
    file = ProjectInitializationFile(project_id=conversation.project_id, conversation_id=conversation.id,
        uploaded_by_user_id=user.id, file_name=name, storage_path=str(path), content_type='image/png',
        file_size=path.stat().st_size, file_hash='synthetic-image')
    db.add(file)
    db.flush()
    if parsed:
        store_parsed_initialization_attachment(db, file, ParsedAttachment(content='原有OCR资料文字',
            parsers=('test-ocr',),segments=1,details={'status':'ready'}))
    else:
        store_failed_initialization_attachment(db, file, '测试OCR不可用')
    db.commit()
    return file


def test_initialization_sends_only_selected_images_and_preserves_ocr_manifest(db, tmp_path):
    user, _, conversation = setup_conversation(db, kind='initialization')
    selected = initial_file(db, tmp_path, conversation, user)
    initial_file(db, tmp_path, conversation, user, name='未选历史图片.png')
    rows = _initialization_files_for_message(db, conversation, [selected.id])
    blocks, native_ids = images.image_blocks_for_turn([], rows, upload_dir=tmp_path)
    assert len(blocks) == 1 and blocks[0]['name'] == selected.file_name
    manifest = _initialization_attachment_manifest_context(db, rows, native_image_ids=native_ids)
    assert 'chunks' in manifest and 'native_images' in manifest
    assert '未选历史图片' not in manifest
    assert '原有OCR资料文字' not in manifest  # Keep the original reference-only context.


def test_failed_ocr_does_not_block_valid_native_image(db, tmp_path):
    user, _, conversation = setup_conversation(db, kind='initialization')
    file = initial_file(db, tmp_path, conversation, user, parsed=False)
    blocks, ids = images.image_blocks_for_turn([], [file], upload_dir=tmp_path)
    assert blocks
    manifest = _initialization_attachment_manifest_context(db, [file], native_image_ids=ids)
    assert 'native_images' in manifest and '"files": []' in manifest
    with pytest.raises(HTTPException):
        _initialization_attachment_manifest_context(db, [file])


def test_other_conversation_and_project_files_cannot_be_selected(db, tmp_path):
    user, _, conversation = setup_conversation(db, kind='initialization')
    other_user, _, other = setup_conversation(db, 'other', kind='initialization')
    foreign = initial_file(db, tmp_path, other, other_user)
    with pytest.raises(HTTPException) as denied:
        _initialization_files_for_message(db, conversation, [foreign.id])
    assert denied.value.status_code == 422


def test_initialization_path_cannot_escape_its_authorized_conversation_directory(db, tmp_path):
    user, _, conversation = setup_conversation(db, kind='initialization')
    file = initial_file(db, tmp_path, conversation, user)
    external = tmp_path / 'unrelated.png'
    external.write_bytes(raw_image())
    file.storage_path = str(external)
    with pytest.raises(HTTPException) as denied:
        images.image_blocks_for_turn([], [file], upload_dir=tmp_path)
    assert denied.value.status_code == 403


def mocked_runtime(monkeypatch, tmp_path):
    client = Mock()
    client.get_catalog.return_value = {'business_agents':[{'id':'agent','name':'测试智能体',
        'enabled':True,'published':True,'role':'business','model_ready':True}]}
    client.chat.return_value = AgentScopeReply(status='completed',content='已看到图片',message_id='reply',raw_message=None)

    @asynccontextmanager
    async def event_stream(*_):
        async def empty():
            if False:
                yield None
        yield empty()

    client.event_stream = event_stream
    monkeypatch.setattr(api, '_agentscope_client', lambda:client)
    monkeypatch.setattr(api, 'get_settings', lambda:SimpleNamespace(upload_dir=tmp_path))
    monkeypatch.setattr(api, '_finalize_agent_reply', lambda *_:{'id':'reply','role':'assistant','content':'已看到图片'})
    return client


@pytest.mark.parametrize('stream', [False, True])
def test_real_business_route_forwards_image_blocks_to_gateway_after_authorization(db, tmp_path, monkeypatch, stream):
    user, _, conversation = setup_conversation(db)
    client = mocked_runtime(monkeypatch, tmp_path)
    payload = AgentConversationMessageInput(content='请检查这张图片。', image_attachments=[inline_image()])
    if stream:
        response = api.stream_agent_conversation_message(conversation.id, payload, db, user)
        async def consume():
            return [part async for part in response.body_iterator]
        parts = asyncio.run(consume())
        assert any('accepted' in part for part in parts)
    else:
        response = api.create_agent_conversation_message(conversation.id, payload, db, user)
        assert response['data']['user_message']['extra_data']['image_attachments'][0]['media_type'] == 'image/png'
    sent = client.chat.call_args.kwargs
    assert sent['content_blocks'][0]['source']['data'] == payload.image_attachments[0].data
    assert sent['metadata']['platform_image_attachments'] == [{'name':'测试图片.png','media_type':'image/png'}]


@pytest.mark.parametrize('stream', [False, True])
def test_foreign_user_cannot_send_images_into_another_users_session(db, tmp_path, monkeypatch, stream):
    owner, _, conversation = setup_conversation(db)
    other = _admin(db, 'unauthorized')
    client = mocked_runtime(monkeypatch, tmp_path)
    function = api.stream_agent_conversation_message if stream else api.create_agent_conversation_message
    with pytest.raises(HTTPException) as denied:
        function(conversation.id, AgentConversationMessageInput(content='看图',image_attachments=[inline_image()]), db, other)
    assert denied.value.status_code == 403
    client.chat.assert_not_called()
