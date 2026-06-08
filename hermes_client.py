#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes Agent API 测试客户端(零依赖,仅用 Python 标准库)

支持的调用方式:
  chat          普通对话 (POST /v1/chat/completions)
  stream        流式对话 + 工具进度 (SSE)
  responses     结构化响应,可看到工具调用过程 (POST /v1/responses)
  health        健康检查 (GET /health)
  capabilities  能力发现 (GET /v1/capabilities)
  models        模型列表 (GET /v1/models)
  skills        技能列表 (GET /v1/skills)
  toolsets      工具集列表 (GET /v1/toolsets)

用法示例:
  python hermes_client.py chat "你好"
  python hermes_client.py chat "列出当前目录的文件" --raw
  python hermes_client.py stream "统计当前目录有多少个文件"
  python hermes_client.py responses "项目里有哪些文件"
  python hermes_client.py health
  python hermes_client.py capabilities

  # 切换到 ordinary profile(端口 8010,用它自己的令牌):
  python hermes_client.py chat "你好" --port 8010 --key <ordinary的令牌>

配置优先级:命令行参数 > 环境变量 > 脚本内默认值
  环境变量:HERMES_HOST / HERMES_PORT / HERMES_KEY
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

# ============ 默认配置(可被环境变量 / 命令行参数覆盖)============
DEFAULT_HOST = "100.106.17.149"
DEFAULT_PORT = 8088
# 出于安全,默认不写死令牌;用 --key 或环境变量 HERMES_KEY 传入
DEFAULT_KEY = "82bcb45b711bfb2e59ab7d8bdc536def98ef4cff031b5aa3e9e72968488213e0"
DEFAULT_TIMEOUT = 180  # Agent 思考+调工具可能较慢,超时放宽
# ===============================================================


def build_base_url(host, port):
    return f"http://{host}:{port}"


def http_request(url, key, method="GET", payload=None, timeout=DEFAULT_TIMEOUT, stream=False):
    """发起 HTTP 请求。返回 (status_code, urllib_response_or_bytes)。
    stream=True 时返回打开的 response 对象供逐行读取;否则返回已读取的 bytes。"""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        if stream:
            return resp.status, resp
        return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        # 4xx/5xx:读出错误体一起返回,便于排查
        body = e.read()
        return e.code, body
    except urllib.error.URLError as e:
        print(f"[连接失败] 无法连接到 {url}", file=sys.stderr)
        print(f"          原因:{e.reason}", file=sys.stderr)
        print(f"          请检查:服务是否在跑、端口是否正确、主机是否可达。", file=sys.stderr)
        sys.exit(2)


def print_error_body(status, body):
    """统一打印非 2xx 的错误响应。"""
    print(f"[HTTP {status}] 请求未成功")
    try:
        obj = json.loads(body)
        err = obj.get("error", obj)
        msg = err.get("message") if isinstance(err, dict) else err
        print(f"  错误信息:{msg}")
        if isinstance(err, dict):
            if err.get("type"):
                print(f"  类型:{err.get('type')}")
            if err.get("code"):
                print(f"  代码:{err.get('code')}")
    except (json.JSONDecodeError, AttributeError):
        print(f"  原始响应:{body.decode('utf-8', errors='replace')}")
    # 给点常见提示
    if status == 401:
        print("  → 多半是令牌错误或缺失,检查 --key / HERMES_KEY 是否与服务端一致。")
    elif status == 405:
        print("  → 方法不被允许,检查接口与 HTTP 方法是否匹配。")


def cmd_chat(args, base_url):
    """普通对话(非流式)。"""
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": "hermes-agent",
        "messages": [{"role": "user", "content": args.prompt}],
    }
    print(f"→ 发送到 {url}")
    print(f"  指令:{args.prompt}\n  (Agent 思考+调用工具中,请稍候...)\n")

    status, body = http_request(url, args.key, method="POST", payload=payload, timeout=args.timeout)
    if status != 200:
        print_error_body(status, body)
        return

    data = json.loads(body)
    if args.raw:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    content = data["choices"][0]["message"]["content"]
    finish = data["choices"][0].get("finish_reason")
    usage = data.get("usage", {})
    print("─" * 60)
    print(content)
    print("─" * 60)
    print(f"结束原因: {finish}  |  "
          f"token: 输入 {usage.get('prompt_tokens')} / "
          f"输出 {usage.get('completion_tokens')} / "
          f"合计 {usage.get('total_tokens')}")
    print(f"响应ID: {data.get('id')}")


def cmd_stream(args, base_url):
    """流式对话:逐 token 输出,并显示工具调用进度。"""
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": "hermes-agent",
        "stream": True,
        "messages": [{"role": "user", "content": args.prompt}],
    }
    print(f"→ 流式请求 {url}")
    print(f"  指令:{args.prompt}\n")

    status, resp = http_request(url, args.key, method="POST", payload=payload,
                                timeout=args.timeout, stream=True)
    if status != 200:
        # 流式失败时 resp 是已打开的对象,读出来
        body = resp.read() if hasattr(resp, "read") else resp
        print_error_body(status, body)
        return

    current_event = None
    printed_any = False
    print("─" * 60)
    try:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
            if not line:
                current_event = None
                continue
            if line.startswith("event:"):
                current_event = line[len("event:"):].strip()
                continue
            if line.startswith("data:"):
                data_str = line[len("data:"):].strip()
                if data_str == "[DONE]":
                    break
                # 工具进度事件:单独提示
                if current_event == "hermes.tool.progress":
                    try:
                        evt = json.loads(data_str)
                        print(f"\n  🔧 [工具] {evt}", flush=True)
                    except json.JSONDecodeError:
                        print(f"\n  🔧 [工具进度] {data_str}", flush=True)
                    continue
                # 普通 chunk:取 delta.content 拼接输出
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    piece = delta.get("content")
                    if piece:
                        print(piece, end="", flush=True)
                        printed_any = True
                except json.JSONDecodeError:
                    pass
    finally:
        resp.close()
    if printed_any:
        print()
    print("─" * 60)
    print("(流结束)")


def cmd_responses(args, base_url):
    """结构化响应:能看到 Agent 调用了哪些工具、得到什么结果。"""
    url = f"{base_url}/v1/responses"
    payload = {
        "model": "hermes-agent",
        "input": args.prompt,
        "store": False,
    }
    print(f"→ 发送到 {url}")
    print(f"  指令:{args.prompt}\n  (处理中...)\n")

    status, body = http_request(url, args.key, method="POST", payload=payload, timeout=args.timeout)
    if status != 200:
        print_error_body(status, body)
        return

    data = json.loads(body)
    if args.raw:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    print(f"状态: {data.get('status')}  |  响应ID: {data.get('id')}")
    print("─" * 60)
    for item in data.get("output", []):
        t = item.get("type")
        if t == "function_call":
            print(f"🔧 调用工具: {item.get('name')}")
            print(f"   参数: {item.get('arguments')}")
        elif t == "function_call_output":
            out = item.get("output", "")
            print(f"   ↳ 结果: {out}")
        elif t == "message":
            texts = []
            for part in item.get("content", []):
                if part.get("type") in ("output_text", "text"):
                    texts.append(part.get("text", ""))
            print("\n💬 最终回复:")
            print("".join(texts))
    print("─" * 60)
    usage = data.get("usage", {})
    print(f"token: 输入 {usage.get('input_tokens')} / "
          f"输出 {usage.get('output_tokens')} / "
          f"合计 {usage.get('total_tokens')}")


def cmd_get_json(args, base_url, path, need_auth=True, title=""):
    """通用 GET 接口:健康检查、能力发现、模型/技能/工具集列表。"""
    url = f"{base_url}{path}"
    key = args.key if need_auth else ""
    status, body = http_request(url, key, method="GET", timeout=args.timeout)
    if status != 200:
        print_error_body(status, body)
        return
    try:
        data = json.loads(body)
        print(f"{title}{url}")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(body.decode("utf-8", errors="replace"))


def main():
    parser = argparse.ArgumentParser(
        description="Hermes Agent API 测试客户端(零依赖)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default=os.environ.get("HERMES_HOST", DEFAULT_HOST),
                        help=f"服务主机(默认 {DEFAULT_HOST},或环境变量 HERMES_HOST)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("HERMES_PORT", DEFAULT_PORT)),
                        help=f"服务端口(默认 {DEFAULT_PORT};ordinary 用 8010)")
    parser.add_argument("--key", default=os.environ.get("HERMES_KEY", DEFAULT_KEY),
                        help="API 令牌(或环境变量 HERMES_KEY)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"超时秒数(默认 {DEFAULT_TIMEOUT})")
    parser.add_argument("--raw", action="store_true", help="打印完整原始 JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    p_chat = sub.add_parser("chat", help="普通对话")
    p_chat.add_argument("prompt", help="要发送的指令/问题")

    p_stream = sub.add_parser("stream", help="流式对话 + 工具进度")
    p_stream.add_argument("prompt", help="要发送的指令/问题")

    p_resp = sub.add_parser("responses", help="结构化响应(看工具调用过程)")
    p_resp.add_argument("prompt", help="要发送的指令/问题")

    sub.add_parser("health", help="健康检查(无需令牌)")
    sub.add_parser("capabilities", help="能力发现")
    sub.add_parser("models", help="模型列表")
    sub.add_parser("skills", help="技能列表")
    sub.add_parser("toolsets", help="工具集列表")

    args = parser.parse_args()
    base_url = build_base_url(args.host, args.port)

    # 需要令牌的命令,提前检查
    need_key_cmds = {"chat", "stream", "responses", "capabilities", "models", "skills", "toolsets"}
    if args.command in need_key_cmds and not args.key:
        print("[缺少令牌] 请用 --key <令牌> 或设置环境变量 HERMES_KEY", file=sys.stderr)
        sys.exit(1)

    if args.command == "chat":
        cmd_chat(args, base_url)
    elif args.command == "stream":
        cmd_stream(args, base_url)
    elif args.command == "responses":
        cmd_responses(args, base_url)
    elif args.command == "health":
        cmd_get_json(args, base_url, "/health", need_auth=False, title="健康检查 ")
    elif args.command == "capabilities":
        cmd_get_json(args, base_url, "/v1/capabilities", title="能力清单 ")
    elif args.command == "models":
        cmd_get_json(args, base_url, "/v1/models", title="模型列表 ")
    elif args.command == "skills":
        cmd_get_json(args, base_url, "/v1/skills", title="技能列表 ")
    elif args.command == "toolsets":
        cmd_get_json(args, base_url, "/v1/toolsets", title="工具集列表 ")


if __name__ == "__main__":
    main()
