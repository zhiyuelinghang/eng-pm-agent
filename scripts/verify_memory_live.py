"""Local end-to-end smoke using an isolated temporary business account/project."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'AgentScope'))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
import httpx
from sqlalchemy import select,delete,text
from backend.app.db import SessionLocal
from backend.app.models import User,Project,ProjectMember,OperationLog
from backend.app.security import create_access_token,hash_password
from utils.memory_service import get_memory_repository


def main():
    marker='memory-smoke-'+uuid4().hex[:12]
    user_id=project_id=conversation_id=None
    report={'marker':marker,'steps':[]}
    client=httpx.Client(base_url='http://127.0.0.1:38430',timeout=150)
    try:
        with SessionLocal() as db:
            user=User(username=marker,password_hash=hash_password(uuid4().hex),role='user',
                real_name='临时记忆验收用户',identity_card_no='MEMTEST-'+uuid4().hex[:20])
            project=Project(name='临时记忆链路验收-'+marker)
            db.add_all([user,project]); db.flush()
            user_id,project_id=user.id,project.id
            db.add(ProjectMember(user_id=user.id,project_id=project.id)); db.commit()
        client.headers['Authorization']='Bearer '+create_access_token(user_id,'user')
        response=client.post(f'/api/projects/{project_id}/agent-conversations',json={'conversation_type':'general','title':'临时记忆验收'})
        response.raise_for_status(); conversation=response.json()['data']; conversation_id=conversation['id']
        report['session_id']=conversation['agentscope_session_id']
        response=client.post(f'/api/agent-conversations/{conversation_id}/messages',json={'content':
            '这是临时账号的记忆链路验收。请调用add_memory保存“验收偏好：周报先列问题，再列责任人”，使用user_project范围和preference.memory_smoke字段。仅调用记忆工具，不调用任何任务、群聊、协作或数据库交互工具。本次不要学习。请简短报告真实结果。'})
        response.raise_for_status()
        report['save_reply']=response.json()
        repository=get_memory_repository()
        with repository._connection() as conn:
            records=conn.execute("SELECT id,version,identity_type,scope_type,status FROM memory_records WHERE platform_user_id=%s AND project_id=%s AND fact_key='preference.memory_smoke'",(str(user_id),str(project_id))).fetchall()
            report['matching_records']=[dict(r) for r in records]
            assert len(records)==1 and records[0]['status']=='active' and records[0]['identity_type']=='business_user','保存记录未匹配'
            row=records[0]
            runs=conn.execute('SELECT no_learning,no_memory FROM memory_runs WHERE root_session_id=%s',(report['session_id'],)).fetchall()
            assert runs and all(run['no_learning'] for run in runs)
            assert conn.execute('SELECT count(*) AS n FROM learning_events WHERE platform_user_id=%s',(str(user_id),)).fetchone()['n']==0
        report['steps'].append('平台HTTP入口→AgentScope真实模型→user_project正式记忆保存成功；真实业务身份正确且不进入学习')
        response=client.post(f'/api/agent-conversations/{conversation_id}/messages',json={'content':
            f'请只调用forget_memory清理本次临时测试记录 {row["id"]}，expected_version={row["version"]}。不要调用业务工具，本次不要学习。简短报告实际结果。'})
        response.raise_for_status()
        with repository._connection() as conn:
            assert conn.execute('SELECT status FROM memory_records WHERE id=%s',(row['id'],)).fetchone()['status']=='deleted'
        report['steps'].append('同一真实平台入口撤回测试记忆成功，停止召回')
        report['status']='passed'
    finally:
        if user_id and project_id:
            from utils.memory_repository import MemoryAccess
            repository=get_memory_repository()
            with repository._connection() as conn:
                remaining=conn.execute("SELECT id,version,tenant_id FROM memory_records WHERE platform_user_id=%s AND project_id=%s AND fact_key='preference.memory_smoke' AND status<>'deleted'",(str(user_id),str(project_id))).fetchall()
            for remaining_row in remaining:
                repository.forget(MemoryAccess(remaining_row['tenant_id'],str(user_id),str(project_id),project_read=True),
                    str(remaining_row['id']),remaining_row['version'])
        if conversation_id:
            cleanup=client.delete(f'/api/agent-conversations/{conversation_id}')
            cleanup.raise_for_status()
        with SessionLocal() as db:
            user=db.get(User,user_id) if user_id else None
            project=db.get(Project,project_id) if project_id else None
            if user and user.username==marker and project and project.name.endswith(marker):
                db.execute(delete(OperationLog).where(OperationLog.operator_id==user_id))
                db.execute(delete(ProjectMember).where(ProjectMember.user_id==user_id,ProjectMember.project_id==project_id))
                db.delete(project); db.delete(user); db.commit()
                report['temporary_business_data_cleaned']=True
        client.close()
        if user_id and project_id:
            get_memory_repository().close()
        (ROOT/'artifacts/memory-live-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='save_reply'},ensure_ascii=False,default=str))


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print('真实记忆验收未完成：'+type(exc).__name__)
        raise SystemExit(1) from None
