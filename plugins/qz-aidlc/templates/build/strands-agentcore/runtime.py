"""Amazon Bedrock AgentCore Runtime entrypoint. Locally: python runtime.py, then POST /invocations.
Deploy with the AgentCore starter toolkit; identity, memory and gateway are configured there, not in code."""
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agent.app import run

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict) -> dict:
    """payload: {"prompt": str, "approve": true | false | null}"""
    res = run(payload.get("prompt", ""), approve=payload.get("approve"))
    return {"result": res["output"], "tool_calls": res["tool_calls"], "awaiting_approval": res["awaiting_approval"], "usage": res["usage"]}


if __name__ == "__main__":
    app.run()
