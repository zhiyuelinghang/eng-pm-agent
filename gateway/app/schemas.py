from datetime import datetime

from pydantic import BaseModel


class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    role: str

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    """C 写入摘要时用的请求体。"""

    project_id: int
    raw_text: str | None = None
    summary: str
    source: str = "wechat"
    source_ref: str | None = None


class MessageOut(BaseModel):
    id: int
    project_id: int
    source: str
    source_ref: str | None = None
    raw_text: str | None = None
    summary: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SkillLogCreate(BaseModel):
    """C 记录一次技能 / 工具调用。"""

    tool_name: str
    project_id: int | None = None
    input_args: str | None = None
    output_result: str | None = None
    status: str = "ok"
    error_message: str | None = None


class SkillLogOut(BaseModel):
    id: int
    tool_name: str
    project_id: int | None = None
    status: str
    input_args: str | None = None
    output_result: str | None = None
    error_message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
