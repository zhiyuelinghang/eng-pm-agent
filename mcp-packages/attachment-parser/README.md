# 附件解析系统工具

该能力在产品中属于平台固定系统工具：所有智能体自动装载，智能体管理端只能
查看，不能分配、取消或删除。实现代码以独立依赖完整包运行，只处理平台以内存
方式传入的附件内容，不接收附件 ID、任意 URL 或服务器文件路径。工程平台通过
[解析桥接层](../../backend/app/system_attachment_parser.py) 复用同一解析内核，
保存文档解析结果供初始化等业务使用。

解析顺序：

1. PDF、图片、DOCX、PPTX、XLSX 按 MinerU 开源版输入范围优先调用
   `MINERU_FILE_PARSE_URL`；
2. MinerU 超时、不可用、拒绝文件或返回无效结果时，自动使用随包携带的本地
   解析器；
3. CSV、TXT、Markdown、旧版 XLS 不发送到 MinerU，直接本地解析；
4. 返回结果中的 `parser` 为 `mineru` 或 `local_fallback`，降级时保留原因。

聊天流水线根据当前模型登记的输入能力区分两条路径：

- 模型支持的图片保留原图，通过原生图片内容块输入，不以解析文本替换；
- 普通文档和不符合原生图片条件的附件在模型执行前调用本工具，遍历所有分页与
  工作表，以 `<parsed-attachments>` 文本替换对应二进制输入。解析失败时传递
  明确的失败状态，原始消息仍保留附件用于下载与审计。

判断和组装以 [附件流水线](../../AgentScope/agentscope/app/_service/_attachment_pipeline.py)
为准。工程平台原图输入的数量、大小和真实格式校验见
[agent_image_attachments.py](../../backend/app/agent_image_attachments.py)。

服务默认值定义在 [解析内核](parser_runtime.py)，平台运行环境可以通过
`MINERU_FILE_PARSE_URL`、`MINERU_BACKEND`、`MINERU_SERVER_URL` 和
`MINERU_TIMEOUT_SECONDS` 覆盖。附件会发送到所配置的 MinerU 服务，部署时应
确认该服务符合项目的数据安全要求。

构建 Windows 依赖完整包：

```powershell
.\python-3.13.14\python.exe scripts\build_attachment_parser_mcp_package.py
```

构建产物位于
`data/agentscope/test-packages/attachment-parser-mcp-windows.zip`。

更新平台固定工具（需要随后重启 AgentScope 服务）：

```powershell
.\python-3.13.14\python.exe scripts\install_system_attachment_parser.py
```
