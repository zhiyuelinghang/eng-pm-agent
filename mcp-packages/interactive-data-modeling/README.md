# 数据分析与预测建模 MCP

这是 `feature/data_analysis_mcp` 分支中数据分析 MCP 的平台适配版本。上游业务
算法与状态机保留在 `src/shield_prediction_mcp`，平台侧新增依赖完整打包、附件
引用、会话隔离、中文工具名称和自动验收。

## 平台使用方式

1. 给智能体分配“数据分析与预测建模” MCP，并建议同时分配
   `build-prediction-model` 技能；
2. 用户在聊天中上传 CSV、TSV、XLS/XLSX、JSON/JSONL 或 Parquet；
3. 平台附件流水线自动调用 `predict_import_data`，只把当前会话有效的
   `predict-data://...` 引用交给模型；
4. 智能体用该引用调用 `predict_create_session`，完成画像、变量确认、方案确认、
   异步训练、测试集评估和模型导出。

平台模式不接受模型构造任意服务器文件路径。上游独立客户端仍可使用本地
`data_path`，两种模式互不影响。

## 构建与安装

首次构建或更新依赖缓存：

```powershell
.\python-3.13.14\python.exe scripts\build_data_analysis_mcp_package.py --refresh-dependencies
```

后续复用缓存构建：

```powershell
.\python-3.13.14\python.exe scripts\build_data_analysis_mcp_package.py
```

运行上传与完整建模冒烟测试：

```powershell
.\python-3.13.14\python.exe scripts\smoke_test_data_analysis_mcp_package.py
```

安装到本地平台目录：

```powershell
.\python-3.13.14\python.exe scripts\install_data_analysis_mcp.py
```

构建产物默认位于
`data/agentscope/test-packages/interactive-data-modeling-mcp-windows.zip`。

完整差异、边界和升级说明见 [平台适配说明.md](平台适配说明.md)。
