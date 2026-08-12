MAX_TEXT_LENGTH = 2048
MAX_MARKDOWN_LENGTH = 4096
MAX_NEWS_ARTICLES = 8
MAX_TITLE_LEN = 128
MAX_DESC_LEN = 512

def validate_news_articles(articles: list) -> list:
    issues = []
    if not isinstance(articles, list) or len(articles) == 0:
        issues.append("articles 必须是非空列表")
        return issues
    if len(articles) > MAX_NEWS_ARTICLES:
        issues.append(f"最多支持 {MAX_NEWS_ARTICLES} 条图文，当前 {len(articles)} 条")
    for i, art in enumerate(articles):
        prefix = f"第 {i+1} 条: "
        if not art.get("title"):
            issues.append(prefix + "缺少 title")
        elif len(art["title"]) > MAX_TITLE_LEN:
            issues.append(prefix + f"title 超过 {MAX_TITLE_LEN} 字符")
        if not art.get("url"):
            issues.append(prefix + "缺少 url")
        if art.get("description") and len(art["description"]) > MAX_DESC_LEN:
            issues.append(prefix + f"description 超过 {MAX_DESC_LEN} 字符")
    return issues



def validate_text_content(content: str) -> list:
    issues = []
    if not content or not content.strip():
        issues.append("消息内容不能为空")
    if len(content) > MAX_TEXT_LENGTH:
        issues.append(f"文本消息长度超过 {MAX_TEXT_LENGTH} 字符")
    return issues

def validate_markdown_content(content: str) -> list:
    issues = []
    if not content or not content.strip():
        issues.append("Markdown内容不能为空")
    if len(content) > MAX_MARKDOWN_LENGTH:
        issues.append(f"Markdown消息长度超过 {MAX_MARKDOWN_LENGTH} 字符")
    return issues
