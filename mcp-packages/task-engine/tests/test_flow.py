"""任务流转的测试：状态机、节点推进、转办与逾期。"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from task_engine.domain.flow import (
    TransitionError,
    accept,
    add_note,
    block_step,
    cancel,
    complete_step,
    forward_step,
    instantiate,
    mark_overdue_if_needed,
    reject,
    skip_step,
    unblock_step,
)
from task_engine.domain.models import (
    ActivityKind,
    Assignee,
    Site,
    StepSpec,
    StepState,
    TaskFlow,
    TaskState,
)

TZ = ZoneInfo("Asia/Shanghai")
T0 = datetime(2026, 3, 2, 9, 0, tzinfo=TZ)

ZHANG = Assignee(ref="u1", display_name="张三")
LI = Assignee(ref="u2", display_name="李四")
WANG = Assignee(ref="u3", display_name="王五")
BOSS = Assignee(ref="boss", display_name="项目经理")
SITE = Site(ref="wbs-3", name="3号楼-地下室", code="WBS-03-B1")


def make_flow(**overrides) -> TaskFlow:
    defaults = dict(
        title="隐患整改闭环",
        steps=(
            StepSpec(name="发现隐患", assignee=ZHANG, due_offset_days=1, deliverable="隐患记录"),
            StepSpec(name="派单整改", assignee=LI, due_offset_days=2, deliverable="整改照片"),
            StepSpec(name="安全员复核", assignee=WANG, due_offset_days=1, deliverable="复核意见"),
        ),
        site=SITE,
        confirmer=BOSS,
    )
    defaults.update(overrides)
    return TaskFlow(**defaults)


class TestInstantiate:
    def test_first_step_is_activated(self):
        task = instantiate(make_flow(), T0)
        assert task.state is TaskState.RUNNING
        assert task.steps[0].state is StepState.ACTIVE
        assert task.steps[1].state is StepState.WAITING

    def test_deadlines_accumulate_across_steps(self):
        task = instantiate(make_flow(), T0)
        assert task.steps[0].due_at == T0 + timedelta(days=1)
        assert task.steps[1].due_at == T0 + timedelta(days=3)
        assert task.steps[2].due_at == T0 + timedelta(days=4)

    def test_task_due_at_is_last_deadline(self):
        task = instantiate(make_flow(), T0)
        assert task.due_at == T0 + timedelta(days=4)

    def test_creation_is_logged(self):
        task = instantiate(make_flow(), T0)
        kinds = [act.kind for act in task.activities]
        assert kinds[0] is ActivityKind.CREATED
        assert ActivityKind.STEP_ACTIVATED in kinds

    def test_current_assignee_is_first_owner(self):
        task = instantiate(make_flow(), T0)
        assert task.current_assignee == ZHANG


class TestStepProgression:
    def test_completing_advances_to_next(self):
        task = instantiate(make_flow(), T0)
        complete_step(task, 0, now=T0, actor="u1")
        assert task.steps[0].state is StepState.DONE
        assert task.steps[1].state is StepState.ACTIVE
        assert task.current_assignee == LI

    def test_all_done_enters_review(self):
        task = instantiate(make_flow(), T0)
        for seq in range(3):
            complete_step(task, seq, now=T0, actor="u1")
        assert task.state is TaskState.REVIEW
        assert task.current_step is None

    def test_progress_counts(self):
        task = instantiate(make_flow(), T0)
        assert task.progress == (0, 3)
        complete_step(task, 0, now=T0)
        assert task.progress == (1, 3)

    def test_cannot_complete_twice(self):
        task = instantiate(make_flow(), T0)
        complete_step(task, 0, now=T0)
        with pytest.raises(TransitionError, match="已经了结"):
            complete_step(task, 0, now=T0)

    def test_attachment_requirement_enforced(self):
        flow = make_flow(
            steps=(
                StepSpec(name="拍照留证", assignee=ZHANG, requires_attachment=True),
                StepSpec(name="复核", assignee=LI),
            ),
        )
        task = instantiate(flow, T0)
        with pytest.raises(TransitionError, match="证明材料"):
            complete_step(task, 0, now=T0)

        complete_step(task, 0, now=T0, attachments=["photo.jpg"])
        assert task.steps[0].state is StepState.DONE

    def test_comment_and_attachments_recorded(self):
        task = instantiate(make_flow(), T0)
        complete_step(task, 0, now=T0, actor="u1", comment="已完成", attachments=["a.pdf"])
        assert task.steps[0].comment == "已完成"
        assert task.steps[0].attachments == ["a.pdf"]


class TestSkip:
    def test_optional_step_can_be_skipped(self):
        flow = make_flow(
            steps=(
                StepSpec(name="执行", assignee=ZHANG),
                StepSpec(name="可选复核", assignee=LI, optional=True),
                StepSpec(name="归档", assignee=WANG),
            ),
        )
        task = instantiate(flow, T0)
        complete_step(task, 0, now=T0)
        skip_step(task, 1, now=T0, reason="无需复核")
        assert task.steps[1].state is StepState.SKIPPED
        assert task.steps[2].state is StepState.ACTIVE

    def test_required_step_cannot_be_skipped(self):
        task = instantiate(make_flow(), T0)
        with pytest.raises(TransitionError, match="必经节点"):
            skip_step(task, 0, now=T0)


class TestForward:
    def test_forward_changes_owner_not_position(self):
        task = instantiate(make_flow(), T0)
        forward_step(task, 0, to=WANG, now=T0, actor="u1", note="我不在现场")
        assert task.steps[0].assignee == WANG
        assert task.steps[0].state is StepState.ACTIVE  # 位置不变
        assert task.current_step.seq == 0

    def test_forward_is_logged(self):
        task = instantiate(make_flow(), T0)
        forward_step(task, 0, to=WANG, now=T0)
        assert task.activities[-1].kind is ActivityKind.FORWARDED
        assert "王五" in task.activities[-1].summary

    def test_cannot_forward_settled_step(self):
        task = instantiate(make_flow(), T0)
        complete_step(task, 0, now=T0)
        with pytest.raises(TransitionError, match="无法转办"):
            forward_step(task, 0, to=WANG, now=T0)

    def test_future_step_can_be_reassigned(self):
        """尚未轮到的节点可以提前改派——排班场景：先安排好后续人手。"""
        task = instantiate(make_flow(), T0)
        forward_step(task, 2, to=ZHANG, now=T0, actor="pm", note="老王那天休假")

        assert task.steps[2].assignee == ZHANG
        assert task.current_step.seq == 0, "改派未来节点不应改变当前流转位置"
        assert task.steps[2].state is StepState.WAITING

    def test_completed_step_keeps_its_owner(self):
        """已完成节点的责任归属不可篡改——这是审计轨迹的基础。"""
        task = instantiate(make_flow(), T0)
        complete_step(task, 0, now=T0, actor="u1")
        original = task.steps[0].assignee

        with pytest.raises(TransitionError):
            forward_step(task, 0, to=WANG, now=T0)
        assert task.steps[0].assignee == original

    def test_skipped_step_cannot_be_reassigned(self):
        flow = make_flow(
            steps=(
                StepSpec(name="可选首步", assignee=ZHANG, optional=True),
                StepSpec(name="次步", assignee=LI),
            ),
        )
        task = instantiate(flow, T0)
        skip_step(task, 0, now=T0, reason="不需要")
        with pytest.raises(TransitionError):
            forward_step(task, 0, to=WANG, now=T0)


class TestBlocking:
    def test_block_and_unblock(self):
        task = instantiate(make_flow(), T0)
        block_step(task, 0, now=T0, reason="等待材料进场")
        assert task.state is TaskState.BLOCKED
        assert task.steps[0].state is StepState.BLOCKED

        unblock_step(task, 0, now=T0)
        assert task.state is TaskState.RUNNING
        assert task.steps[0].state is StepState.ACTIVE

    def test_unblock_requires_blocked_step(self):
        task = instantiate(make_flow(), T0)
        with pytest.raises(TransitionError, match="未受阻"):
            unblock_step(task, 0, now=T0)


class TestReviewAndClose:
    def _finish_all(self):
        task = instantiate(make_flow(), T0)
        for seq in range(3):
            complete_step(task, seq, now=T0)
        return task

    def test_accept_closes_task(self):
        task = self._finish_all()
        accept(task, now=T0, actor="boss")
        assert task.state is TaskState.DONE
        assert task.closed_at == T0

    def test_reject_reopens_last_step(self):
        task = self._finish_all()
        reject(task, now=T0, actor="boss", reason="照片不清晰")
        assert task.state is TaskState.RUNNING
        assert task.steps[2].state is StepState.ACTIVE
        assert task.current_step.seq == 2

    def test_accept_requires_review_state(self):
        task = instantiate(make_flow(), T0)
        with pytest.raises(TransitionError, match="待验收"):
            accept(task, now=T0)

    def test_terminal_task_rejects_further_operations(self):
        task = self._finish_all()
        accept(task, now=T0)
        with pytest.raises(TransitionError, match="不能继续操作"):
            complete_step(task, 0, now=T0)


class TestCancel:
    def test_cancel_from_running(self):
        task = instantiate(make_flow(), T0)
        cancel(task, now=T0, reason="项目暂停")
        assert task.state is TaskState.CANCELLED
        assert task.closed_at == T0

    def test_cannot_cancel_twice(self):
        task = instantiate(make_flow(), T0)
        cancel(task, now=T0)
        with pytest.raises(TransitionError):
            cancel(task, now=T0)


class TestOverdue:
    def test_marks_overdue_past_deadline(self):
        task = instantiate(make_flow(), T0)
        later = T0 + timedelta(days=10)
        assert mark_overdue_if_needed(task, now=later) is True
        assert task.state is TaskState.OVERDUE

    def test_no_change_before_deadline(self):
        task = instantiate(make_flow(), T0)
        assert mark_overdue_if_needed(task, now=T0 + timedelta(hours=1)) is False
        assert task.state is TaskState.RUNNING

    def test_closed_task_never_overdue(self):
        task = instantiate(make_flow(), T0)
        cancel(task, now=T0)
        assert mark_overdue_if_needed(task, now=T0 + timedelta(days=99)) is False

    def test_overdue_is_idempotent(self):
        task = instantiate(make_flow(), T0)
        later = T0 + timedelta(days=10)
        assert mark_overdue_if_needed(task, now=later) is True
        assert mark_overdue_if_needed(task, now=later) is False

    def test_overdue_task_can_resume(self):
        task = instantiate(make_flow(), T0)
        mark_overdue_if_needed(task, now=T0 + timedelta(days=10))
        complete_step(task, 0, now=T0 + timedelta(days=10))
        assert task.state is TaskState.RUNNING


class TestNotes:
    def test_note_recorded_without_advancing(self):
        task = instantiate(make_flow(), T0)
        add_note(task, now=T0, actor="u1", note="现场已确认")
        assert task.activities[-1].kind is ActivityKind.NOTE_ADDED
        assert task.current_step.seq == 0

    def test_empty_note_rejected(self):
        task = instantiate(make_flow(), T0)
        with pytest.raises(TransitionError, match="不能为空"):
            add_note(task, now=T0, note="   ")


class TestAccountabilityRequirements:
    """工程责任制三要素：谁负责、在哪个工点、由谁确认。

    这三项在模板阶段可以留空（便于复用），但布置成真实待办前必须齐备——
    否则就会出现「有任务没人认领」或「完成了没人验收」的情况。
    """

    def test_abstract_role_cannot_be_an_assignee(self):
        """责任人必须是具体的人，不能是「安全员」这类岗位。

        岗位到人的解析属于宿主系统的组织架构职责，引擎只认具体标识。
        """
        # ref 为空直接拒绝——这是唯一能挡住"未落到人"的技术手段
        with pytest.raises(ValueError, match="不能为空"):
            Assignee(ref="")
        with pytest.raises(ValueError, match="不能为空"):
            Assignee(ref="   ")

    def test_dispatch_rejects_unassigned_step(self):
        flow = make_flow(
            steps=(
                StepSpec(name="发现隐患", assignee=ZHANG),
                StepSpec(name="整改"),                      # 没有责任人
                StepSpec(name="复核", assignee=WANG),
            ),
        )
        with pytest.raises(ValueError, match="尚未指定责任人"):
            instantiate(flow, T0)

    def test_error_names_the_unassigned_steps(self):
        flow = make_flow(
            steps=(StepSpec(name="发现隐患"), StepSpec(name="整改")),
        )
        with pytest.raises(ValueError, match="第 1 个「发现隐患」"):
            instantiate(flow, T0)

    def test_dispatch_rejects_missing_confirmer(self):
        flow = make_flow(confirmer=None)
        with pytest.raises(ValueError, match="确认人"):
            instantiate(flow, T0)

    def test_dispatch_rejects_missing_site(self):
        flow = make_flow(site=None)
        with pytest.raises(ValueError, match="工点"):
            instantiate(flow, T0)

    def test_complete_flow_can_be_dispatched(self):
        task = instantiate(make_flow(), T0)
        assert task.site == SITE
        assert task.confirmer == BOSS
        assert all(step.assignee is not None for step in task.steps)

    def test_template_may_leave_blanks(self):
        """模板阶段允许留空，只有布置时才强制。"""
        flow = TaskFlow(
            title="可复用模板",
            steps=(StepSpec(name="执行"), StepSpec(name="复核")),
        )
        assert len(flow.unassigned_steps()) == 2   # 定义本身合法

    def test_site_is_carried_into_task(self):
        task = instantiate(make_flow(), T0)
        assert task.site.code == "WBS-03-B1"
        assert "3号楼" in str(task.site)

    def test_site_appears_in_creation_log(self):
        task = instantiate(make_flow(), T0)
        assert "3号楼" in task.activities[0].summary


class TestConfirmerAuthority:
    """完成后由谁确认——验收权限必须限定到人。"""

    def _finish_all(self):
        task = instantiate(make_flow(), T0)
        for seq in range(3):
            complete_step(task, seq, now=T0)
        return task

    def test_only_confirmer_can_accept(self):
        task = self._finish_all()
        with pytest.raises(TransitionError, match="只有确认人"):
            accept(task, now=T0, actor="u1")      # 张三不是确认人

    def test_confirmer_can_accept(self):
        task = self._finish_all()
        accept(task, now=T0, actor="boss")
        assert task.state is TaskState.DONE

    def test_only_confirmer_can_reject(self):
        task = self._finish_all()
        with pytest.raises(TransitionError, match="只有确认人"):
            reject(task, now=T0, actor="u2", reason="材料不全")

    def test_confirmer_can_reject(self):
        task = self._finish_all()
        reject(task, now=T0, actor="boss", reason="材料不全")
        assert task.state is TaskState.RUNNING

    def test_error_names_the_confirmer(self):
        task = self._finish_all()
        with pytest.raises(TransitionError, match="项目经理"):
            accept(task, now=T0, actor="u1")

    def test_system_call_is_allowed(self):
        """actor 为空视为系统调用——引擎不承担身份认证职责。"""
        task = self._finish_all()
        accept(task, now=T0)
        assert task.state is TaskState.DONE


class TestValidation:
    def test_flow_requires_title(self):
        with pytest.raises(ValueError, match="标题不能为空"):
            TaskFlow(title="  ", steps=(StepSpec(name="x"),))

    def test_flow_requires_steps(self):
        with pytest.raises(ValueError, match="至少需要一个节点"):
            TaskFlow(title="任务", steps=())

    def test_step_requires_name(self):
        with pytest.raises(ValueError, match="节点名称不能为空"):
            StepSpec(name="")


class TestOrderEnforcement:
    """流转顺序必须强制——否则「没整改先归档」就成了可能。"""

    def test_cannot_skip_ahead(self):
        task = instantiate(make_flow(), T0)
        with pytest.raises(TransitionError, match="不能跨越"):
            complete_step(task, 2, now=T0)

    def test_error_names_the_expected_step(self):
        task = instantiate(make_flow(), T0)
        with pytest.raises(TransitionError, match="发现隐患"):
            complete_step(task, 2, now=T0)

    def test_in_order_completion_works(self):
        task = instantiate(make_flow(), T0)
        for seq in range(3):
            complete_step(task, seq, now=T0)
        assert task.state is TaskState.REVIEW

    def test_cannot_skip_ahead_with_skip_step(self):
        flow = make_flow(
            steps=(
                StepSpec(name="第一步", assignee=ZHANG),
                StepSpec(name="可选第二步", assignee=LI, optional=True),
            ),
        )
        task = instantiate(flow, T0)
        with pytest.raises(TransitionError, match="不能跨越"):
            skip_step(task, 1, now=T0)


class TestBlockedNodeCompletion:
    """完成受阻节点后，任务状态必须跟着恢复，不能与节点状态脱节。"""

    def test_completing_blocked_step_resumes_task(self):
        task = instantiate(make_flow(), T0)
        block_step(task, 0, now=T0, reason="等材料")
        assert task.state is TaskState.BLOCKED

        complete_step(task, 0, now=T0)
        assert task.state is TaskState.RUNNING, "任务应恢复运行，而不是卡在 blocked"
        assert task.steps[1].state is StepState.ACTIVE

    def test_skipping_blocked_step_resumes_task(self):
        flow = make_flow(
            steps=(
                StepSpec(name="可选首步", assignee=ZHANG, optional=True),
                StepSpec(name="次步", assignee=LI),
            ),
        )
        task = instantiate(flow, T0)
        block_step(task, 0, now=T0, reason="等材料")
        skip_step(task, 0, now=T0, reason="不需要了")
        assert task.state is TaskState.RUNNING


class TestRejectRequiresFreshEvidence:
    """退回重做时必须重新提交材料——否则「照片不清晰，重拍」的退回形同虚设。"""

    def _flow_with_evidence(self):
        return TaskFlow(
            title="整改闭环",
            steps=(
                StepSpec(name="整改并拍照", assignee=ZHANG,
                         deliverable="整改后照片", requires_attachment=True),
            ),
            site=SITE,
            confirmer=BOSS,
        )

    def test_old_attachments_survive_reject(self):
        """旧附件保留——审计轨迹不可抹去。"""
        task = instantiate(self._flow_with_evidence(), T0)
        complete_step(task, 0, now=T0, actor="u1", attachments=["第一次.jpg"])
        reject(task, now=T0, actor="boss", reason="照片不清晰")

        assert task.steps[0].attachments == ["第一次.jpg"]
        assert task.steps[0].reopened is True

    def test_cannot_reuse_old_attachment_after_reject(self):
        task = instantiate(self._flow_with_evidence(), T0)
        complete_step(task, 0, now=T0, actor="u1", attachments=["第一次.jpg"])
        reject(task, now=T0, actor="boss", reason="照片不清晰，重拍")

        with pytest.raises(TransitionError, match="重新提交证明材料"):
            complete_step(task, 0, now=T0, actor="u1")

    def test_fresh_attachment_accepted_after_reject(self):
        task = instantiate(self._flow_with_evidence(), T0)
        complete_step(task, 0, now=T0, actor="u1", attachments=["第一次.jpg"])
        reject(task, now=T0, actor="boss", reason="重拍")
        complete_step(task, 0, now=T0, actor="u1", attachments=["重拍的.jpg"])

        assert task.state is TaskState.REVIEW
        assert task.steps[0].attachments == ["第一次.jpg", "重拍的.jpg"]
        assert task.steps[0].reopened is False

    def test_first_submission_may_reuse_existing_attachments(self):
        """首次提交时沿用已上传的附件是允许的——只有重做才要求新材料。"""
        task = instantiate(self._flow_with_evidence(), T0)
        task.steps[0].attachments.append("预先上传.jpg")
        complete_step(task, 0, now=T0, actor="u1")

        assert task.steps[0].state is StepState.DONE

    def test_step_without_evidence_requirement_unaffected(self):
        flow = TaskFlow(
            title="普通流程",
            steps=(StepSpec(name="执行", assignee=ZHANG),),
            site=SITE, confirmer=BOSS,
        )
        task = instantiate(flow, T0)
        complete_step(task, 0, now=T0, actor="u1")
        reject(task, now=T0, actor="boss", reason="重做")
        complete_step(task, 0, now=T0, actor="u1")  # 不要求留证，可直接完成

        assert task.state is TaskState.REVIEW
