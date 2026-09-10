"""Run the unified-memory regressions using disposable PostgreSQL test schemas."""
from pathlib import Path
import argparse
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / '.env')

TESTS = [
    'AgentScope/tests/test_memory_run_integration.py',
    'AgentScope/tests/test_memory_repository.py',
    'AgentScope/tests/test_learning_pipeline.py',
    'AgentScope/tests/test_learning_context_authorization.py',
    'AgentScope/tests/test_learning_failure_sources.py',
    'AgentScope/tests/test_learning_source_policy.py',
    'AgentScope/tests/test_business_learning_consumer.py',
    'AgentScope/tests/test_group_learning.py',
    'AgentScope/tests/test_memory_current_sources.py',
    'AgentScope/tests/test_memory_source_visibility.py',
    'AgentScope/tests/test_memory_learning_migration.py',
    'AgentScope/tests/test_agent_memory_policy_removal.py',
    'AgentScope/tests/test_agent_memory_config.py',
    'AgentScope/tests/test_memory_tool_policy.py',
    'AgentScope/tests/test_unified_memory.py',
    'AgentScope/tests/test_workspace_tool_policy.py',
    'AgentScope/tests/test_platform_integration.py',
    'AgentScope/tests/test_fixed_knowledge_tool_factory.py',
    'AgentScope/tests/test_knowledge_assistant_assignment.py',
    'AgentScope/tests/test_dobby_architecture_runtime.py',
    'AgentScope/tests/test_agent_call_allowlist.py',
    'AgentScope/tests/test_collaboration_policy.py',
    'AgentScope/tests/test_debug_permissions.py',
    'backend/tests/test_business_learning_policy.py',
    'backend/tests/test_business_learning_sources.py',
    'backend/tests/test_business_learning_postgres_transaction.py',
    'backend/tests/test_group_agent_authorization.py',
    'backend/tests/test_group_learning_source.py',
    'backend/tests/test_task_assistant_generation.py',
    'backend/tests/test_task_assistant_mcp_draft.py',
    'backend/tests/test_initialization_agent_orchestration.py',
    'backend/tests/test_initialization_skill_provision.py',
    'backend/tests/test_knowledge_agent_entry.py',
]

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', default='artifacts/memory-unified-final-tests.log')
    parser.add_argument('tests', nargs='*')
    args = parser.parse_args()
    environment = dict(os.environ)
    database_url = environment.get('DOBBY_MEMORY_TEST_DATABASE_URL') or environment.get('DATABASE_URL', '')
    if not database_url.startswith(('postgresql://', 'postgresql+psycopg://')):
        raise SystemExit('需要已配置的 PostgreSQL 测试连接；不自动创建或替换数据库。')
    environment['DOBBY_MEMORY_TEST_DATABASE_URL'] = database_url.replace('postgresql+psycopg://', 'postgresql://', 1)
    command = [sys.executable, '-X', 'utf8', 'scripts/pytest_entry.py',
        '--prepend', '.', '--prepend', 'AgentScope', '--prepend', 'mcp-packages/task-engine/src',
        '--', *(args.tests or TESTS), '-q']
    log = ROOT / args.log
    with log.open('w', encoding='utf-8') as output:
        result = subprocess.run(command, cwd=ROOT, env=environment, stdout=output, stderr=subprocess.STDOUT)
    print(log.read_text(encoding='utf-8')[-24000:])
    raise SystemExit(result.returncode)
