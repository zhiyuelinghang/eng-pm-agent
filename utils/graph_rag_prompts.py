"""
GraphRAG entity type guidance for engineering safety domain.

LightRAG uses addon_params={'entity_types_guidance': '...'} to
override the default generic entity types (Person, Organization, etc.)
with domain-specific types for construction/engineering safety.
"""

# Injected into LightRAG's entity_extraction_system_prompt via
# addon_params={'entity_types_guidance': ENTITY_TYPES_GUIDANCE}
ENTITY_TYPES_GUIDANCE = """实体类型（仅限以下类型，不要使用其他类型）:
  - 规范条款: 具体的法规/标准条款，如"GB 6095-2021 §5.2"
  - 安全措施: 防护设备/措施，如"安全带"、"防护栏杆"、"安全网"
  - 风险类型: 事故/隐患分类，如"高处坠落"、"物体打击"、"触电"
  - 检查项: 安全检查的具体项目，如"脚手架稳固性检查"
  - 材料: 工程材料，如"C35混凝土"、"Q235钢材"
  - 工艺: 施工工艺/方法，如"焊接工艺"、"混凝土浇筑"
  - 责任主体: 角色/单位，如"安全员"、"监理单位"
  - 项目阶段: 工程生命周期阶段，如"地基施工"、"主体封顶"

关系类型（仅限以下类型，不要使用其他类型）:
  - 规范要求: 规范条款要求采取某安全措施
  - 引用: 规范/条款之间的交叉引用
  - 预防: 安全措施预防某风险类型
  - 包含: 检查项属于某规范条款
  - 适用于: 规范条款适用于某项目阶段
  - 使用: 工艺使用某材料
  - 负责: 责任主体负责某检查项

以上列表是完整的——不要编造不在列表中的实体类型或关系类型。"""
