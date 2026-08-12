import requests
import os
from dotenv import load_dotenv
import base64
import hashlib

load_dotenv()

def send_image(image_source):
    """
    发送图片到群机器人。
    image_source: 本地文件路径 或 base64 字符串（可带或不带 data URI 头）
    """
    url = get_webhook_url()

    if not image_source.startswith("data:image"):
        # 本地文件路径
        with open(image_source, "rb") as f:
            raw_data = f.read()
    else:
        # base64 字符串，去掉 data URI 头，然后解码得到原始字节
        header, base64_part = image_source.split(",", 1)
        raw_data = base64.b64decode(base64_part)

    # 计算 MD5
    md5_hash = hashlib.md5(raw_data).hexdigest()

    # 重新编码为不含头部的纯 base64，并移除换行符
    b64_str = base64.b64encode(raw_data).decode().replace("\n", "")

    body = {
        "msgtype": "image",
        "image": {
            "base64": b64_str,
            "md5": md5_hash
        }
    }

    try:
        resp = requests.post(url, json=body, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        return result.get("errcode") == 0, result
    except Exception as e:
        return False, {"error": str(e)}

def get_webhook_url() -> str:
    url = os.getenv("WECOM_WEBHOOK_URL")
    if not url:
        raise ValueError("环境变量 WECOM_WEBHOOK_URL 未设置")
    return url

def send_text(content: str, mentioned_list=None, mentioned_mobile_list=None):
    """发送文本消息到群机器人，返回 (success, response_json)"""
    url = get_webhook_url()
    body = {
        "msgtype": "text",
        "text": {
            "content": content,
        }
    }
    if mentioned_list:
        body["text"]["mentioned_list"] = mentioned_list
    if mentioned_mobile_list:
        body["text"]["mentioned_mobile_list"] = mentioned_mobile_list

    try:
        resp = requests.post(url, json=body, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        return result.get("errcode") == 0, result
    except Exception as e:
        return False, {"error": str(e)}

def send_markdown(content: str):
    """发送Markdown消息到群机器人，返回 (success, response_json)"""
    url = get_webhook_url()
    body = {
        "msgtype": "markdown",
        "markdown": {
            "content": content
        }
    }
    try:
        resp = requests.post(url, json=body, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        return result.get("errcode") == 0, result
    except Exception as e:
        return False, {"error": str(e)}

def send_news(articles: list):
    """
    发送图文消息（1~8 条）。
    articles: [{"title":..., "description":..., "url":..., "picurl":...}, ...]
    """
    url = get_webhook_url()
    body = {
        "msgtype": "news",
        "news": {
            "articles": articles
        }
    }
    try:
        resp = requests.post(url, json=body, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        return result.get("errcode") == 0, result
    except Exception as e:
        return False, {"error": str(e)}
