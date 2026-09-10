"""Adapt the output allowance to model capabilities and remaining context."""
from ...middleware import MiddlewareBase


class ManagedModelMiddleware(MiddlewareBase):
    async def on_model_call(self, agent, input_kwargs, next_handler):
        model = input_kwargs["current_model"]
        target = getattr(model, "_managed_output_limit", None)
        if target is not None and hasattr(model.parameters, "max_tokens"):
            used = await model.count_tokens(
                input_kwargs["messages"], input_kwargs.get("tools"),
            )
            # Token counting is an estimate; reserve room for provider framing.
            available = max(1, model.context_size - used - 1024)
            model.parameters.max_tokens = min(target, available)
            if hasattr(model.parameters, "thinking_budget"):
                budget = getattr(model, "_managed_thinking_budget", None)
                if budget is not None:
                    model.parameters.thinking_budget = min(
                        budget, max(0, model.parameters.max_tokens - 1024),
                    )
        return await next_handler(**input_kwargs)
