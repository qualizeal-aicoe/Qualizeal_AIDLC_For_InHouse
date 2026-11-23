"""The model gateway: one setting, AGENT_GATEWAY=litellm, sends every model call through the LiteLLM proxy described in
gateway/litellm.yaml, at AGENT_GATEWAY_URL, with the gateway's own key (AGENT_GATEWAY_KEY).

The provider keys live in the proxy's environment and nowhere else: in gateway mode the agent refuses to start while a
provider key is in its own environment. Each model call carries the run's trace context (traceparent), so the
gateway's record of the call (model, tokens, cost) lands inside the run's trace in Langfuse. The tools, the approval
gate and the limits are the same with or without the gateway."""
import os
from urllib.parse import urlsplit

PROVIDER_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AZURE_OPENAI_API_KEY",
                 "AZURE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "MISTRAL_API_KEY", "COHERE_API_KEY")


def on() -> bool:
    return os.environ.get("AGENT_GATEWAY", "").strip().lower() == "litellm"


def url() -> str:
    return os.environ.get("AGENT_GATEWAY_URL", "http://127.0.0.1:4000").rstrip("/")


def model(small: bool = False) -> str:
    """The gateway's model names (model_name in gateway/litellm.yaml), never a provider's: the gateway picks the provider."""
    return (os.environ.get("AGENT_GATEWAY_MODEL_SMALL", "") if small else "") or os.environ.get("AGENT_GATEWAY_MODEL", "agent-model")


def key() -> str:
    held = [k for k in PROVIDER_KEYS if os.environ.get(k)]
    if held:
        raise SystemExit(f"With AGENT_GATEWAY=litellm the gateway holds the provider keys: unset {', '.join(held)} where the agent runs.")
    k = os.environ.get("AGENT_GATEWAY_KEY", "")
    if not k:
        raise SystemExit("Set AGENT_GATEWAY_KEY to the gateway's key: a LiteLLM virtual key (its master key only on a laptop).")
    return k


def host() -> str:
    return (urlsplit(url()).hostname or "").lower()


def trace_context() -> dict:
    """The current span's W3C trace context, so the gateway files its record of the call inside the run's trace."""
    from opentelemetry.propagate import inject
    carrier: dict = {}
    inject(carrier)
    return carrier


def httpx_client(asynchronous: bool = False, timeout: float = 60.0):
    """An HTTP client that adds the trace context to every request; the OpenAI and Anthropic SDKs take one (httpx2 for
    the OpenAI SDK 3, httpx before it)."""
    try:
        import httpx2 as httpx
    except ImportError:
        import httpx
    if asynchronous:
        async def add_async(request):
            request.headers.update(trace_context())
        return httpx.AsyncClient(event_hooks={"request": [add_async]}, timeout=httpx.Timeout(timeout, connect=10.0))

    def add(request):
        request.headers.update(trace_context())
    return httpx.Client(event_hooks={"request": [add]}, timeout=httpx.Timeout(timeout, connect=10.0))


def claude_code_env(model_name: str) -> dict:
    """For Claude Code under the Claude Agent SDK: the gateway as its API with the gateway key as its bearer token, the
    gateway's small model for its background calls, the run's trace context on every request, and no traffic outside
    the gateway path."""
    env = {"ANTHROPIC_BASE_URL": url(), "ANTHROPIC_AUTH_TOKEN": key(), "ANTHROPIC_MODEL": model_name,
           "ANTHROPIC_DEFAULT_HAIKU_MODEL": model(small=True), "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    ctx = trace_context()
    if ctx:
        env["ANTHROPIC_CUSTOM_HEADERS"] = "\n".join(f"{k}: {v}" for k, v in ctx.items())
    return env


def content_in_traces() -> bool:
    """Prompt and answer text go into traces only when the team turns it on (AGENT_TRACE_CONTENT=1); off by default."""
    return os.environ.get("AGENT_TRACE_CONTENT", "") == "1"
