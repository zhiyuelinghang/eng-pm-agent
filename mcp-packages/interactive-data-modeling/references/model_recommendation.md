# 通用表格数据预测模型推荐规则

## 决策逻辑

- 少于 500 条：优先 XGBoost、Random Forest、Linear/Logistic；中等维度可加入 SVM。
- 500–5000 条：优先 XGBoost、Random Forest、MLP，并保留线性基线。
- 大于 5000 条：优先 XGBoost、MLP、Random Forest。
- 存在明确顺序或时间依赖：500 条以上推荐 LSTM、1D-CNN，同时使用 XGBoost 建立可解释基线。
- 用户明确指定模型时尊重选择，但在依赖、样本量或时序结构不匹配时返回提示。

## Agent 训练计划

`propose_training_plan` 不只推荐模型，还会组合：

- 主模型与可解释基线
- random、sequential 或保留测试集的真实 KFold
- 70/15/15 等比例方案
- default、random、bayesian 或 grid 调参策略
- 用户的精度、速度、可解释性和训练预算偏好

返回结果必须同时包含推荐方案和全部合法备选项。Agent 负责解释和整理用户修改，MCP 负责依赖探测、组合约束、参数校验和最终计划持久化。

## 默认参数

参数由 `src/shield_prediction_mcp/modeling.py` 中的 `DEFAULT_PARAMS` 统一管理，并写入每次训练和导出的配置文件。

## 通用任务示例

| 目标 | 常用模型 | 说明 |
|---|---|---|
| 客户流失分类 | XGBoost、Random Forest、Logistic Regression | 同时兼顾非线性效果与可解释基线 |
| 销量或能耗回归 | XGBoost、Random Forest、Linear Regression | 适合常见混合型表格特征 |
| 设备指标时序预测 | LSTM、1D-CNN、XGBoost | 数据存在明确时间依赖 |
| 风险等级分类 | XGBoost、Random Forest、SVM | 适合中小规模分类数据 |
