import { documents, processRecords, projects, tasks } from "./data.js";

const today = new Date("2026-06-16T09:00:00");

export function getProject(projectId) {
  return projects.find((project) => project.id === projectId) ?? projects[0];
}

export function getProjectRecords(projectId) {
  return processRecords.filter((record) => record.projectId === projectId);
}

export function getProjectTasks(projectId) {
  return tasks.filter((task) => task.projectId === projectId);
}

export function getProjectDocuments(projectId) {
  return documents.filter((document) => document.projectId === projectId);
}

export function getSource(sourceId) {
  return processRecords.find((record) => record.id === sourceId);
}

export function matchProjectByText(text) {
  const normalized = text.toLowerCase();
  return projects.find((project) => [project.name, ...project.aliases].some((name) => normalized.includes(name.toLowerCase())));
}

export function summarizeProject(projectId) {
  const project = getProject(projectId);
  const records = getProjectRecords(projectId);
  const projectTasks = getProjectTasks(projectId);
  const projectDocs = getProjectDocuments(projectId);
  const openTasks = projectTasks.filter((task) => !["已完成", "已关闭"].includes(task.status));
  const overdueTasks = projectTasks.filter((task) => isOverdue(task));
  const missingDocs = getMissingDocuments(projectId);
  const latestRecord = records.at(-1);

  return {
    project,
    progress: latestRecord?.content ?? "暂无过程记录。",
    openTaskCount: openTasks.length,
    overdueTaskCount: overdueTasks.length,
    missingDocCount: missingDocs.length,
    documentCompletion: Math.round(((projectDocs.length - missingDocs.length) / project.requiredDocs.length) * 100),
    riskLevel: overdueTasks.length > 0 || missingDocs.length > 0 ? "需关注" : "正常",
    sources: latestRecord ? [latestRecord.id] : [],
  };
}

export function isOverdue(task) {
  if (["已完成", "已关闭"].includes(task.status)) {
    return false;
  }
  return new Date(`${task.dueDate}T23:59:59`) < today;
}

export function getMissingDocuments(projectId) {
  return getProjectDocuments(projectId).filter((document) => document.status === "缺失");
}

export function findDocuments(projectId, keyword) {
  const docs = getProjectDocuments(projectId);
  if (!keyword) {
    return docs;
  }
  return docs.filter((document) => {
    const source = getSource(document.sourceId);
    const haystack = `${document.name} ${document.type} ${document.status} ${source?.content ?? ""}`;
    return haystack.toLowerCase().includes(keyword.toLowerCase());
  });
}

export function extractTasksFromMeeting(projectId) {
  const meetings = getProjectRecords(projectId).filter((record) => record.sourceType === "会议纪要");
  const existingTitles = new Set(getProjectTasks(projectId).map((task) => task.title));
  return meetings.flatMap((meeting) => {
    const matches = meeting.content.match(/[^。；;]*?(提交|补交|复核|确认|补设|补齐|巡查)[^。；;]*/g) ?? [];
    return matches
      .map((line, index) => ({
        id: `draft-${meeting.id}-${index}`,
        projectId,
        title: line.replace(/^会议要求/, "").trim(),
        owner: inferOwner(line),
        dueDate: inferDueDate(line),
        status: "待确认",
        type: inferTaskType(line),
        sourceIds: [meeting.id],
        needsInfo: line.includes("确认"),
      }))
      .filter((task) => !existingTitles.has(task.title));
  });
}

export function buildProactiveQuestions(projectId) {
  return getProjectTasks(projectId)
    .filter((task) => task.needsInfo || isOverdue(task))
    .map((task) => ({
      taskId: task.id,
      receiver: task.owner,
      question: `请确认“${task.title}”当前进展：[A] 已完成 [B] 处理中 [C] 需要协调 [D] 其他说明`,
      sourceIds: task.sourceIds,
    }));
}

export function buildOverdueReminders(projectId) {
  return getProjectTasks(projectId)
    .filter((task) => isOverdue(task))
    .map((task) => ({
      taskId: task.id,
      receiver: task.owner,
      message: `提醒：${task.title} 已超过截止时间 ${task.dueDate}，请补充进展和闭环证据。`,
      sourceIds: task.sourceIds,
    }));
}

export function generateWeeklyReport(projectId) {
  const summary = summarizeProject(projectId);
  const records = getProjectRecords(projectId);
  const projectTasks = getProjectTasks(projectId);
  const missingDocs = getMissingDocuments(projectId);
  const completedTasks = projectTasks.filter((task) => ["已完成", "已关闭"].includes(task.status));
  const openTasks = projectTasks.filter((task) => !completedTasks.includes(task));

  return {
    title: `${summary.project.name} 周报初稿`,
    body: [
      `本周阶段：${summary.project.stage}。`,
      `主要进展：${records.map((record) => record.content).join(" ")}`,
      `已完成事项：${completedTasks.map((task) => task.title).join("；") || "暂无"}`,
      `未闭环事项：${openTasks.map((task) => `${task.title}（${task.owner}，${task.dueDate}）`).join("；") || "暂无"}`,
      `资料缺失：${missingDocs.map((document) => document.name).join("；") || "暂无"}`,
      "建议动作：优先处理逾期事项，并要求责任人补充来源凭证。",
    ],
    sourceIds: [...new Set([...records.map((record) => record.id), ...projectTasks.flatMap((task) => task.sourceIds)])],
  };
}

export function answerQuestion(projectId, question) {
  const matchedProject = matchProjectByText(question);
  const targetProjectId = matchedProject?.id ?? projectId;
  const summary = summarizeProject(targetProjectId);
  const lowerQuestion = question.toLowerCase();

  if (question.includes("周报") || question.includes("报告")) {
    const report = generateWeeklyReport(targetProjectId);
    return formatAnswer(report.title, report.body, report.sourceIds);
  }

  if (question.includes("资料") || question.includes("齐全") || lowerQuestion.includes("document")) {
    const missingDocs = getMissingDocuments(targetProjectId);
    const lines = missingDocs.length
      ? [`资料不完整，缺失 ${missingDocs.length} 项：${missingDocs.map((document) => document.name).join("、")}。`]
      : ["资料清单当前无缺失项。"];
    return formatAnswer("资料检查", lines, missingDocs.map((document) => document.sourceId));
  }

  if (question.includes("待办") || question.includes("逾期") || question.includes("任务")) {
    const projectTasks = getProjectTasks(targetProjectId);
    const lines = projectTasks.map((task) => `${task.title}：${task.status}，责任人/单位 ${task.owner}，截止 ${task.dueDate}`);
    return formatAnswer("任务进展", lines, [...new Set(projectTasks.flatMap((task) => task.sourceIds))]);
  }

  if (question.includes("追问") || question.includes("信息不足")) {
    const questions = buildProactiveQuestions(targetProjectId);
    const lines = questions.map((item) => `向 ${item.receiver} 追问：${item.question}`);
    return formatAnswer("主动追问", lines.length ? lines : ["当前没有必须主动追问的信息缺口。"], questions.flatMap((item) => item.sourceIds));
  }

  const lines = [
    `${summary.project.name} 当前处于“${summary.project.stage}”，状态为“${summary.project.status}”。`,
    `开放待办 ${summary.openTaskCount} 项，逾期 ${summary.overdueTaskCount} 项，缺失资料 ${summary.missingDocCount} 项。`,
    `最新过程信息：${summary.progress}`,
  ];
  return formatAnswer("项目状态", lines, summary.sources);
}

function formatAnswer(title, lines, sourceIds) {
  return {
    title,
    text: `${title}\n${lines.join("\n")}`,
    sourceIds: [...new Set(sourceIds.filter(Boolean))],
  };
}

function inferOwner(text) {
  const owners = ["施工单位", "安全员", "王经理", "质量员", "资料员", "赵经理", "施工队"];
  return owners.find((owner) => text.includes(owner)) ?? "待确认";
}

function inferDueDate(text) {
  const match = text.match(/6月(\d{1,2})日前/);
  if (match) {
    return `2026-06-${match[1].padStart(2, "0")}`;
  }
  if (text.includes("周三")) {
    return "2026-06-17";
  }
  return "2026-06-19";
}

function inferTaskType(text) {
  if (text.includes("资料") || text.includes("记录")) {
    return "资料归档";
  }
  if (text.includes("安全") || text.includes("围挡") || text.includes("警示")) {
    return "安全整改";
  }
  if (text.includes("复核") || text.includes("质量")) {
    return "质量检查";
  }
  return "协调事项";
}
