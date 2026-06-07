from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from .database import Base


# ============================================================
# 第一阶段就要用的最小表
# ============================================================
class User(Base):
    """用户。"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    display_name = Column(String(64))
    role = Column(String(32), default="member")  # 全局角色：admin / member
    created_at = Column(DateTime, default=datetime.utcnow)


class Project(Base):
    """项目。"""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text)
    status = Column(String(32), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)


class ProjectMember(Base):
    """项目成员：用户与项目的关联，决定用户能看哪些项目。"""

    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_user"),)

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(32), default="member")


class Message(Base):
    """原始信息 / 摘要：C 把项目动态摘要写进来。

    summary 是动态摘要；source / source_ref 用于来源追溯
    （对应参考设计的 evidence 思想：结论要能说清依据来自哪里）。
    todos / weekly_report 为预留字段，前期不填。
    """

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    source = Column(String(32), default="wechat")  # wechat / email / file ...
    source_ref = Column(String(256))  # 原始来源标识：群名、消息ID、文件名等
    raw_text = Column(Text)
    summary = Column(Text)
    # 预留字段（前期不启用）
    todos = Column(Text)
    weekly_report = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class FileObject(Base):
    """文件：记录上传到 MinIO 的对象元数据。"""

    __tablename__ = "files"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    filename = Column(String(256), nullable=False)
    object_key = Column(String(512), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================
# 后期表（任务智能体系统）——先建好，第一阶段代码暂不使用
# 接 LangGraph 做长周期协同任务时启用，避免后期改表
# ============================================================
class AgentJob(Base):
    """智能体任务：一个长周期、带状态、可暂停恢复的任务。"""

    __tablename__ = "agent_jobs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    goal = Column(Text, nullable=False)
    # created / planning / running / waiting_tool / waiting_human
    # / reviewing / completed / failed / cancelled
    status = Column(String(32), default="created")
    priority = Column(Integer, default=0)
    current_step = Column(Integer, default=0)
    result_summary = Column(Text)
    deadline = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentStep(Base):
    """任务步骤：一个任务被拆解成的有序步骤。"""

    __tablename__ = "agent_steps"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("agent_jobs.id"), nullable=False)
    step_order = Column(Integer, nullable=False)
    step_name = Column(String(128))
    # tool_call / human_request / llm_reasoning
    # / database_query / report_generation / approval
    step_type = Column(String(32))
    status = Column(String(32), default="pending")
    input_data = Column(Text)
    output_data = Column(Text)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class HumanRequest(Base):
    """人员协同请求：智能体向人发起的结构化确认。"""

    __tablename__ = "human_requests"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("agent_jobs.id"))
    step_id = Column(Integer, ForeignKey("agent_steps.id"))
    project_id = Column(Integer, ForeignKey("projects.id"))
    target_user_id = Column(Integer, ForeignKey("users.id"))
    target_role = Column(String(32))
    question = Column(Text, nullable=False)
    status = Column(String(16), default="pending")  # pending / answered / timeout / cancelled
    response = Column(Text)
    response_time = Column(DateTime)
    deadline = Column(DateTime)
    remind_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class ToolRegistry(Base):
    """工具注册表：智能体只能调用注册过的工具，受权限与风险等级约束。"""

    __tablename__ = "tool_registry"

    id = Column(Integer, primary_key=True)
    tool_name = Column(String(64), unique=True, nullable=False)
    description = Column(Text)
    input_schema = Column(Text)
    output_schema = Column(Text)
    permission_required = Column(String(64))
    is_readonly = Column(Integer, default=1)  # 1=只读, 0=有副作用
    risk_level = Column(String(16), default="low")  # low / medium / high
    enabled = Column(Integer, default=1)


class ToolCallLog(Base):
    """工具调用日志：每次工具调用留痕。

    第一阶段的“技能调用记录（B8）”即用本表的最小子集。
    """

    __tablename__ = "tool_call_logs"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("agent_jobs.id"))
    step_id = Column(Integer, ForeignKey("agent_steps.id"))
    project_id = Column(Integer, ForeignKey("projects.id"))
    tool_name = Column(String(64), nullable=False)
    input_args = Column(Text)
    output_result = Column(Text)
    status = Column(String(16), default="ok")
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class EvidenceRecord(Base):
    """证据 / 来源记录：智能体给结论时，依据来自哪里。"""

    __tablename__ = "evidence_records"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("agent_jobs.id"))
    project_id = Column(Integer, ForeignKey("projects.id"))
    source_type = Column(String(32))  # message / file / human_reply ...
    source_id = Column(BigInteger)
    summary = Column(Text)
    file_path = Column(String(512))
    message_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
