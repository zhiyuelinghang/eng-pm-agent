import pytest
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import AssistantMsg, ThinkingBlock, TextBlock, HintBlock, ToolCallBlock, ToolResultBlock


@pytest.mark.asyncio
async def test_compatible_reasoning_is_preserved_across_tools_and_team_feedback():
    messages = [AssistantMsg(name='助手', content=[
        ThinkingBlock(thinking='先读取资料'),
        ToolCallBlock(id='read', name='read', input='{}'),
        ToolResultBlock(id='read', name='read', output='资料'),
        ThinkingBlock(thinking='核对读取结果'), TextBlock(text='已读取'),
        HintBlock(hint='专家已完成'),
        ThinkingBlock(thinking='根据反馈复核'),
        ToolCallBlock(id='check', name='check', input='{}'),
        ToolResultBlock(id='check', name='check', output='完成'),
        TextBlock(text='请核对'),
    ])]
    formatted = await OpenAIChatFormatter(preserve_reasoning_content=True).format(messages)
    assistant = [m for m in formatted if m['role']=='assistant']
    assert [m['reasoning_content'] for m in assistant] == ['先读取资料','核对读取结果','根据反馈复核','']
    assert [m['tool_calls'][0]['id'] for m in assistant if m.get('tool_calls')] == ['read','check']
    ordinary = await OpenAIChatFormatter().format(messages)
    assert all('reasoning_content' not in m for m in ordinary)


def test_deepseek_compatible_model_uses_reasoning_replay_without_changing_custom_formatter():
    from agentscope.model import OpenAIChatModel
    from agentscope.credential import OpenAICredential
    credential = OpenAICredential(api_key='test-key', base_url='http://127.0.0.1:1/v1')
    model = OpenAIChatModel(credential=credential, model='deepseek-flash')
    assert model.formatter.preserve_reasoning_content
    ordinary = OpenAIChatModel(credential=credential, model='gpt-test')
    assert not ordinary.formatter.preserve_reasoning_content
    explicit = OpenAIChatFormatter()
    assert OpenAIChatModel(credential=credential, model='deepseek-flash', formatter=explicit).formatter is explicit
