from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .api import router
from .config import get_settings
from .db import Base, SessionLocal, engine
from .models import (Attachment, DailyReport, DocumentFolder, DocumentFolderItem, Project, ProjectChange,
                     ProjectInformationRecord, ProjectMember, ProjectStatusSnapshot, QualityMetric, RiskSource,
                     Task, User, WbsItem, WbsRiskLink)
from .security import hash_password


def seed_admin() -> None:
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.username == "admin")):
            db.add(User(username="admin", real_name="系统管理员", password_hash=hash_password("ChangeMe123!"), role="superadmin"))
            db.commit()


MISSEEDED_DEMO_PROJECTS = ("燃气站改造项目", "3号楼主体结构项目", "市政管网更新项目")
PROTOTYPE_PROJECT = {
    "project_name": "普陀区真如镇街道社区卫生服务中心异地扩建项目",
    "owner_unit": "上海真如城市副中心发展有限公司",
    "description": "综合功能社区医院，地上6层、地下2层（含人防），总建筑面积约20992平方米；当前处于施工阶段，合同工期为2024年9月10日至2027年9月9日。",
    "folders": (
        "00_项目总览",
        "01_合同图纸与方案",
        "02_进度计划",
        "03_质量安全管理",
        "04_监测检测与试验",
        "05_会议沟通与过程记录",
        "06_问题整改与任务闭环",
        "07_变更签证",
        "08_验收移交",
        "09_影像与原始数据",
        "10_AI整理成果",
        "99_归档与历史版本",
    ),
}
MISSEEDED_REQUIRED_DOCUMENT_FOLDERS = ("施工合同", "施工组织设计", "总进度计划", "人员名单", "风险清单", "质量指标关联表")


def ensure_prototype_status_data(db, project: Project) -> None:
    """将原型中归属普陀项目的状态数据初始化到可持久化业务表中。"""
    member_specs = [
        ("prototype_wang_manager", "王经理", "项目经理", "project_manager"),
        ("prototype_zhao_safety", "赵安全", "安全员", "safety_officer"),
        ("prototype_liu_docs", "刘资料", "资料员", "document_controller"),
        ("prototype_chen_contract", "陈施工", "施工单位", "contractor"),
        ("prototype_zhou_supervisor", "周监理", "监理", "supervisor"),
        ("prototype_sun_monitor", "孙监测", "监测单位", "monitoring_unit"),
    ]
    users: dict[str, User] = {}
    for username, real_name, title, member_role in member_specs:
        account = db.scalar(select(User).where(User.username == username))
        if not account:
            account = User(username=username, real_name=real_name, title=title, password_hash=hash_password("ChangeMe123!"), role="member")
            db.add(account)
            db.flush()
        users[real_name] = account
        if not db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == account.id)):
            db.add(ProjectMember(project_id=project.id, user_id=account.id, member_role=member_role, display_name=real_name, responsibilities=[title]))

    supervision_specs = [
        {"code": "WBS-02", "name": "支撑安装", "progress": 90, "status": "delayed", "owner": "陈施工", "yesterday": "完成北侧第一道支撑", "today": "验收资料复核", "quality": "支撑验收记录缺失，轴力资料待核查", "risk": "未完成验收前不得进入下一层开挖", "focus": "支撑验收资料、监测频次确认", "key": True},
        {"code": "WBS-03", "name": "分层开挖", "progress": 92, "status": "in_progress", "owner": "王经理", "yesterday": "准备开挖至-4.5m", "today": "等待开挖条件确认", "quality": "开挖条件核查中", "risk": "S3测斜位移18mm，接近20mm预警阈值", "focus": "开挖前条件、监测复核、临边防护", "key": True},
        {"code": "WBS-04", "name": "降水运行", "progress": 96, "status": "in_progress", "owner": "赵安全", "yesterday": "降水井运行正常", "today": "持续巡查边坡渗水", "quality": "降水记录连续性不足", "risk": "降雨前需检查排水沟、集水井和备用泵", "focus": "降水记录补齐、夜间巡查记录", "key": False},
        {"code": "WBS-05", "name": "临边防护", "progress": 90, "status": "delayed", "owner": "赵安全", "yesterday": "发现西侧局部缺失", "today": "施工单位整改并上传照片", "quality": "整改照片待复核", "risk": "临边防护缺失影响开挖安全条件", "focus": "整改照片、复核意见、闭环证据", "key": True},
    ]
    wbs: dict[str, WbsItem] = {}
    for spec in supervision_specs:
        item = db.scalar(select(WbsItem).where(WbsItem.project_id == project.id, WbsItem.name == spec["name"]))
        if not item:
            item = WbsItem(project_id=project.id, code=spec["code"], name=spec["name"], level=2, planned_start="2026-07-01", planned_finish="2026-07-31", progress=spec["progress"], status=spec["status"], responsible_user_id=users[spec["owner"]].id, raw_data={"supervision": {key: spec[key] for key in ("yesterday", "today", "quality", "risk", "focus", "key")}})
            db.add(item)
            db.flush()
        wbs[spec["name"]] = item

    risk_specs = [
        ("支撑未验收", "medium", "施工风险", "陈施工", "开挖前完成支撑验收、补齐轴力资料和监测频次确认。"),
        ("测斜位移接近预警", "high", "监测预警", "孙监测", "核验S3原始监测数据，确认前不得扩大开挖作业面。"),
        ("临边防护缺失", "medium", "安全隐患", "赵安全", "补齐双道栏杆和警示标识，复核照片作为闭环依据。"),
    ]
    risks: dict[str, RiskSource] = {}
    for name, level, risk_type, owner, control in risk_specs:
        item = db.scalar(select(RiskSource).where(RiskSource.project_id == project.id, RiskSource.name == name))
        if not item:
            item = RiskSource(project_id=project.id, name=name, level=level, risk_type=risk_type, planned_start="2026-07-01", planned_finish="2026-07-31", responsible_user_id=users[owner].id, confirmer_user_id=users["赵安全"].id, material_requirements=["监测日报", "复核意见"], control_requirements=control)
            db.add(item)
            db.flush()
        risks[name] = item

    for wbs_name, risk_name, basis in [
        ("支撑安装", "支撑未验收", "支撑验收完成前不得进入下一层开挖。"),
        ("分层开挖", "测斜位移接近预警", "开挖至-4.5m且S3位移达到18mm时触发复核。"),
        ("临边防护", "临边防护缺失", "临边防护整改照片经复核后方可闭环。"),
    ]:
        if not db.scalar(select(WbsRiskLink).where(WbsRiskLink.wbs_item_id == wbs[wbs_name].id, WbsRiskLink.risk_source_id == risks[risk_name].id)):
            db.add(WbsRiskLink(project_id=project.id, wbs_item_id=wbs[wbs_name].id, risk_source_id=risks[risk_name].id, alert_days=1, notify_methods=["系统通知"], basis=basis))

    quality_specs = [
        ("支撑轴力与验收资料一致性", "支撑安装", "支撑验收记录缺失，轴力资料待核查", "pending"),
        ("降水记录连续性", "降水运行", "降水井运行记录需补齐并保持连续", "processing"),
    ]
    for name, wbs_name, requirement, status in quality_specs:
        if not db.scalar(select(QualityMetric).where(QualityMetric.project_id == project.id, QualityMetric.name == name)):
            db.add(QualityMetric(project_id=project.id, wbs_item_id=wbs[wbs_name].id, name=name, requirement=requirement, inspection_frequency="每日核查", required_materials=["施工日报", "验收记录"], owner_user_id=users["赵安全"].id, status=status))

    def workflow(phase: str, closure: str, rows: list[tuple[str, str, str, str]]) -> list[dict[str, str]]:
        return [{"name": name, "owner": owner, "status": status, "note": material, "material": material, "phase": phase, "closure": closure} for name, owner, status, material in rows]

    task_specs = [
        {"title": "开挖前支撑验收条件核查", "type": "risk_alert", "risk": "medium", "owner": "赵安全", "wbs": "支撑安装", "risk_name": "支撑未验收", "due": "2026-07-20", "status": "pending", "source": "深基坑专项会纪要、深基坑专项施工方案.pdf", "materials": ["支撑验收记录", "监测频次确认"], "steps": workflow("启动", "未闭环", [("AI发起核查", "AI", "completed", "会议纪要/专项方案"), ("安全员条件复核", "赵安全", "pending", "支撑验收记录、监测频次确认"), ("项目经理确认", "王经理", "pending", "开挖条件确认意见")])},
        {"title": "复核S3测斜位移接近预警", "type": "risk_alert", "risk": "high", "owner": "孙监测", "wbs": "分层开挖", "risk_name": "测斜位移接近预警", "due": "2026-07-15", "status": "overdue", "source": "基坑监测日报.xlsx", "materials": ["原始监测数据", "复核意见"], "steps": workflow("过程", "待复核", [("监测平台触发", "监测平台", "completed", "基坑监测日报.xlsx"), ("监测单位复核", "孙监测", "blocked", "原始监测数据"), ("安全员监督确认", "赵安全", "pending", "复核意见")])},
        {"title": "整改西侧临边防护缺失", "type": "risk_alert", "risk": "medium", "owner": "赵安全", "wbs": "临边防护", "risk_name": "临边防护缺失", "due": "2026-07-20", "status": "pending", "source": "巡检照片-临边防护.jpg", "materials": ["整改照片", "复核意见"], "steps": workflow("复核", "未闭环", [("发现隐患", "赵安全", "completed", "巡检照片"), ("施工单位整改", "陈施工", "processing", "整改照片"), ("安全员复核", "赵安全", "pending", "复核意见"), ("闭环归档", "刘资料", "pending", "整改闭环清单")])},
        {"title": "补齐降水井运行记录", "type": "material_missing", "risk": "low", "owner": "刘资料", "wbs": "降水运行", "risk_name": None, "due": "2026-07-21", "status": "pending", "source": "6月18日施工日报", "materials": ["降水井运行记录"], "steps": workflow("过程", "未闭环", [("AI识别缺失", "AI", "completed", "施工日报"), ("资料员补齐", "刘资料", "processing", "降水井运行记录"), ("安全员抽查", "赵安全", "pending", "抽查意见")])},
        {"title": "完成冠梁验收资料归档", "type": "material_missing", "risk": "low", "owner": "刘资料", "wbs": "支撑安装", "risk_name": None, "due": "2026-07-14", "status": "completed", "source": "6月18日施工日报", "materials": ["冠梁验收资料"], "steps": workflow("归档", "已闭环", [("安全员确认验收", "赵安全", "completed", "验收照片"), ("资料员归档", "刘资料", "completed", "冠梁验收资料"), ("闭环确认", "赵安全", "completed", "闭环记录")])},
    ]
    for spec in task_specs:
        if not db.scalar(select(Task).where(Task.project_id == project.id, Task.title == spec["title"])):
            db.add(Task(project_id=project.id, title=spec["title"], task_type=spec["type"], risk_level=spec["risk"], status=spec["status"], assignee_user_id=users[spec["owner"]].id, confirmer_user_id=users["赵安全"].id, due_at=spec["due"], wbs_item_id=wbs[spec["wbs"]].id, risk_source_id=risks[spec["risk_name"]].id if spec["risk_name"] else None, trigger_reason=spec["source"], required_materials=spec["materials"], workflow_steps=spec["steps"]))

    information_specs = [
        ("微信群", "深基坑施工群", "张工", "2026-06-18 17:42", "待确认", "中", "北侧第一道支撑完成，明天计划开挖至-4.5m，监测点S3今日位移接近预警值。"),
        ("日报", "6月18日施工日报", "施工单位", "2026-06-18 20:00", "已入库", "高", "完成冠梁验收、降水井运行正常，夜间安排专人巡查边坡渗水。"),
        ("照片", "巡检照片-临边防护.jpg", "安全员", "2026-06-18 16:10", "待复核", "中", "AI识别：基坑西侧临边防护局部缺失，建议生成整改任务。"),
        ("平台导出", "基坑监测日报.xlsx", "监测平台", "2026-06-18 08:30", "待复核", "高", "S3测斜位移18mm，距预警阈值20mm较近，需人工核验数据来源。"),
        ("会议纪要", "深基坑专项会纪要", "项目部", "2026-06-17 16:30", "已入库", "高", "会议要求开挖前完成支撑验收、降水记录复核、监测频次确认，安全员负责临边防护复查。"),
        ("工程文件", "深基坑专项施工方案.pdf", "技术部", "2026-06-12 09:10", "已入库", "高", "方案包含分层开挖、支撑施工、降水监测、边坡防护和应急处置要求。"),
    ]
    for source_type, source_name, author, recorded_at, status, confidence, content in information_specs:
        if not db.scalar(select(ProjectInformationRecord).where(ProjectInformationRecord.project_id == project.id, ProjectInformationRecord.source_name == source_name)):
            db.add(ProjectInformationRecord(project_id=project.id, source_type=source_type, source_name=source_name, author=author, recorded_at=recorded_at, status=status, confidence=confidence, content=content))

    folders = {item.name: item.id for item in db.scalars(select(DocumentFolder).where(DocumentFolder.project_id == project.id)).all()}
    attachment_specs = [
        ("深基坑专项施工方案.pdf", "专项方案", "01_合同图纸与方案"),
        ("基坑监测日报.xlsx", "监测报告", "04_监测检测与试验"),
        ("巡检照片-临边防护.jpg", "照片", "09_影像与原始数据"),
        ("深基坑专项会纪要", "会议纪要", "05_会议沟通与过程记录"),
        ("冠梁验收资料归档表.pdf", "验收资料", "08_验收移交"),
    ]
    for file_name, category, folder_name in attachment_specs:
        attachment = db.scalar(select(Attachment).where(Attachment.project_id == project.id, Attachment.file_name == file_name))
        if not attachment:
            attachment = Attachment(project_id=project.id, file_name=file_name, storage_path=f"prototype://{file_name}", content_type="application/octet-stream", file_size=0, version=1, category=category, source_type="prototype_seed")
            db.add(attachment)
            db.flush()
        if folder_name in folders and not db.get(DocumentFolderItem, attachment.id):
            db.add(DocumentFolderItem(attachment_id=attachment.id, folder_id=folders[folder_name], project_id=project.id))

    if not db.scalar(select(DailyReport).where(DailyReport.project_id == project.id, DailyReport.file_name == "6月18日施工日报")):
        db.add(DailyReport(project_id=project.id, file_name="6月18日施工日报", report_date="2026-06-18", content="完成冠梁验收、降水井运行正常，夜间安排专人巡查边坡渗水。", matched_wbs_id=wbs["降水运行"].id, confidence=0.9, parse_status="parsed", status="confirmed"))

    change_specs = [
        ("计划节点变更", "开挖计划节点调整", "分层开挖节点根据支撑验收资料复核情况顺延半天，待确认后进入下一层开挖。", "2026-06-18 18:00", ["深基坑施工群", "深基坑专项会纪要"]),
        ("重要人员变更", "S3监测复核责任调整", "S3监测复核由安全员协调调整为监测单位直接反馈，项目经理保留复核确认。", "2026-06-18 18:20", ["基坑监测日报.xlsx"]),
        ("技术方案变更", "临边防护整改技术措施补充", "西侧临边防护整改增加双道栏杆和警示标识，复核照片作为闭环依据。", "2026-06-18 19:10", ["巡检照片-临边防护.jpg"]),
    ]
    for category, title, content, occurred_at, source_refs in change_specs:
        row = db.scalar(select(ProjectChange).where(ProjectChange.project_id == project.id, ProjectChange.title == title))
        if not row:
            row = ProjectChange(project_id=project.id, category=category, title=title, content=content, status="pending", source_refs=source_refs, created_at=datetime.fromisoformat(occurred_at))
            db.add(row)
        else:
            row.category = category
            row.content = content
            row.source_refs = source_refs
            row.created_at = datetime.fromisoformat(occurred_at)

    if not db.get(ProjectStatusSnapshot, project.id):
        db.add(ProjectStatusSnapshot(project_id=project.id, progress_rate=92, progress_status="正常", planned_delta="滞后3%", risk_warnings=1, safety_issues=1, quality_issues=2, task_completion_rate=35, main_risk="S3测斜位移18mm，距预警阈值20mm较近", main_safety="基坑西侧临边防护局部缺失", main_quality="支撑验收资料待核查、降水记录连续性不足", overall="风险可控但需尽快完成复核和资料闭环"))


def seed_prototype_project() -> None:
    with SessionLocal() as db:
        for project in db.scalars(select(Project).where(Project.project_name.in_(MISSEEDED_DEMO_PROJECTS))).all():
            if project.description and project.description.startswith("原型项目："):
                db.query(DocumentFolder).filter(DocumentFolder.project_id == project.id).delete()
                db.delete(project)
        project = db.scalar(select(Project).where(Project.project_name == PROTOTYPE_PROJECT["project_name"]))
        if not project:
            project = Project(
                project_name=PROTOTYPE_PROJECT["project_name"],
                owner_unit=PROTOTYPE_PROJECT["owner_unit"],
                description=PROTOTYPE_PROJECT["description"],
            )
            db.add(project)
            db.flush()
        else:
            project.owner_unit = PROTOTYPE_PROJECT["owner_unit"]
            project.description = PROTOTYPE_PROJECT["description"]
        stale_folders = db.scalars(select(DocumentFolder).where(
            DocumentFolder.project_id == project.id,
            DocumentFolder.parent_id.is_(None),
            DocumentFolder.name.in_(MISSEEDED_REQUIRED_DOCUMENT_FOLDERS),
        )).all()
        stale_ids = [folder.id for folder in stale_folders]
        if stale_ids:
            protected_ids = set(db.scalars(select(DocumentFolderItem.folder_id).where(DocumentFolderItem.folder_id.in_(stale_ids))).all())
            protected_ids.update(db.scalars(select(DocumentFolder.parent_id).where(DocumentFolder.parent_id.in_(stale_ids))).all())
            for folder in stale_folders:
                if folder.id not in protected_ids:
                    db.delete(folder)
        folder_names = set(db.scalars(select(DocumentFolder.name).where(DocumentFolder.project_id == project.id, DocumentFolder.parent_id.is_(None))).all())
        for name in PROTOTYPE_PROJECT["folders"]:
            if name not in folder_names:
                db.add(DocumentFolder(project_id=project.id, name=name))
        db.flush()
        ensure_prototype_status_data(db, project)
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_admin()
    seed_prototype_project()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
