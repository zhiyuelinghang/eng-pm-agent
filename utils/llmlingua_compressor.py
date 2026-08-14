"""
LLMLingua-2 Prompt Compressor — BERT-based high-speed compression (§5.1).

Provides an optional alternative to LLM-based compression. LLMLingua-2
uses a fine-tuned BERT model (microsoft/llmlingua-2-bert-base-multilingual-
cased-meetingbank) to perform token-level binary classification (keep/drop),
achieving ~20x compression with only ~1.5% performance loss.

Key advantages over LLM compression:
  - Zero API cost (runs locally)
  - ~500ms vs 3-10s for LLM
  - Preserves structured sections (compress=False for system/user/tasks)

Usage:
    compressor = LLMLinguaCompressor(ratio=0.5)
    compressed = compressor.compress(long_prompt)
    compressed_msgs = compressor.compress_messages(msgs, protected_indices={0, -1})
"""

from __future__ import annotations

from typing import Any, Optional

from . import config as _cfg

# ── Lazy-loaded model reference ──
_llmlingua_model: Optional[Any] = None


class LLMLinguaCompressor:
    """BERT-based prompt compressor using LLMLingua-2.

    Args:
        ratio: target compression ratio (fraction of tokens to KEEP, default 0.5)
        use_gpu: whether to use GPU acceleration (default False)
        post_summarize: whether to run LLM summarization after compression
    """

    def __init__(
        self,
        ratio: float = 0.5,
        use_gpu: bool = False,
        post_summarize: bool = True,
    ):
        self._ratio = ratio
        self._use_gpu = use_gpu
        self._post_summarize = post_summarize

    # ── Public API ──────────────────────────────────────────

    def compress(self, prompt: str, target_ratio: float = None) -> str:
        """Compress a single prompt string.

        Args:
            prompt: the text to compress
            target_ratio: override the instance ratio (fraction to KEEP)

        Returns:
            Compressed text with low-information tokens removed.
            Falls back to original text if model unavailable.
        """
        model = self._get_model()
        if model is None:
            return prompt

        ratio = target_ratio if target_ratio is not None else self._ratio

        try:
            # LLMLingua-2 API: compress with target compression ratio
            result = model.compress_prompt(
                prompt,
                rate=ratio,  # Fraction of tokens to keep
                force_tokens=["!", ".", "?", "\n"],  # Never drop these
                chunk_end_tokens=["\n", "。"],  # Respect sentence boundaries
                return_word_label=False,  # Faster, no debugging info
            )
            if isinstance(result, dict):
                return result.get("compressed_prompt", prompt)
            return result if isinstance(result, str) else prompt
        except Exception:
            return prompt

    def compress_messages(
        self,
        msgs: list,
        target_ratio: float = None,
        protected_indices: set = None,
        protected_roles: set = None,
    ) -> list:
        """Compress a list of messages, protecting system and user messages.

        Args:
            msgs: list of messages (AgentScope Msg, dict, or string)
            target_ratio: override compression ratio
            protected_indices: set of message indices to NEVER compress
            protected_roles: set of roles to NEVER compress (e.g., {"system", "user"})

        Returns:
            New list with text content compressed. Non-text messages pass through.
            Messages at protected indices remain unchanged.
        """
        ratio = target_ratio if target_ratio is not None else self._ratio
        if protected_indices is None:
            protected_indices = set()
        if protected_roles is None:
            protected_roles = {"system", "user"}

        result = []
        for i, msg in enumerate(msgs):
            if i in protected_indices:
                result.append(msg)
                continue

            role = _get_role(msg)
            if role in protected_roles:
                result.append(msg)
                continue

            # Extract text
            text = _extract_text(msg)
            if not text or len(text) < 50:
                # Too short to compress meaningfully
                result.append(msg)
                continue

            # Compress the text
            compressed = self.compress(text, target_ratio=ratio)

            # Reconstruct message with compressed text
            result.append(_replace_content(msg, compressed))

        return result

    # ── Internal ────────────────────────────────────────────

    def _get_model(self):
        """Lazy-load the LLMLingua-2 model on first use."""
        global _llmlingua_model
        if _llmlingua_model is not None:
            return _llmlingua_model

        try:
            from llmlingua import PromptCompressor

            _llmlingua_model = PromptCompressor(
                model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
                use_llmlingua2=True,  # Use LLMLingua-2 (not v1)
                device_map="cuda" if self._use_gpu else "cpu",
            )
            return _llmlingua_model
        except ImportError:
            import warnings
            warnings.warn(
                "LLMLingua-2 not installed. Install with: pip install llmlingua2\n"
                "Falling back to LLM-based compression.",
                RuntimeWarning,
            )
            return None
        except Exception:
            import warnings
            warnings.warn(
                "Failed to load LLMLingua-2 model. Falling back to LLM-based compression.",
                RuntimeWarning,
            )
            return None


# ============================================================
# Async wrapper — for use in LangGraph nodes
# ============================================================


async def compress_via_llmlingua(
    msgs: list,
    ratio: float = None,
    use_gpu: bool = False,
    protected_roles: set = None,
) -> list:
    """Async wrapper around LLMLinguaCompressor for LangGraph integration.

    Args:
        msgs: messages to compress
        ratio: compression ratio (default from config)
        use_gpu: GPU acceleration
        protected_roles: roles to protect from compression

    Returns:
        Compressed message list
    """
    import asyncio

    if ratio is None:
        ratio = getattr(_cfg, "LLMLINGUA2_RATIO", 0.5)
    if protected_roles is None:
        protected_roles = {"system", "user"}

    compressor = LLMLinguaCompressor(
        ratio=ratio,
        use_gpu=use_gpu or getattr(_cfg, "LLMLINGUA2_USE_GPU", False),
    )

    # Run compression in thread pool (BERT is synchronous)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: compressor.compress_messages(
            msgs,
            target_ratio=ratio,
            protected_roles=protected_roles,
        ),
    )
    return result


# ============================================================
# Internal helpers
# ============================================================


def _get_role(msg: Any) -> str:
    """Extract role from any message type."""
    if hasattr(msg, "role"):
        return msg.role
    if isinstance(msg, dict):
        return msg.get("role", "")
    return ""


def _extract_text(msg: Any) -> str:
    """Extract plain text from any message object."""
    content = ""
    if hasattr(msg, "content"):
        content = msg.content
    elif isinstance(msg, dict):
        content = msg.get("content", "")
    elif isinstance(msg, str):
        return msg

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
            else:
                parts.append(str(block))
        return "".join(parts)
    if hasattr(content, "text"):
        return content.text
    return str(content) if content else ""


def _replace_content(msg: Any, new_text: str) -> Any:
    """Replace the text content of a message, preserving type."""
    if hasattr(msg, "content"):
        if isinstance(msg.content, str):
            msg.content = new_text
        elif isinstance(msg.content, list) and msg.content:
            # Replace first text block
            for i, block in enumerate(msg.content):
                if hasattr(block, "text") or (
                    isinstance(block, dict) and "text" in block
                ):
                    if hasattr(block, "text"):
                        block.text = new_text
                    else:
                        block["text"] = new_text
                    break
            else:
                # No text block found, append
                if hasattr(msg.content, "append"):
                    msg.content.append({"text": new_text, "type": "text"})
    elif isinstance(msg, dict):
        msg["content"] = new_text
    return msg
