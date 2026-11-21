# Open source first

The default at every layer is the open-source or open-weight option, unless the person or the team names a vendor.
A vendor choice is legitimate: record it (`qz practices set standards.vendors anthropic --yes`, with the reason in an
ADR) so `qz stack` knows it was deliberate, and keep the open option one setting away. "Free" is not free to run: open
weights move cost from tokens to hosting, upgrades and security, so start with the layer that matters most.

Licences checked on 21 November 2026. They change per release: confirm on the model card or the repository before you
commit a client to one.

## The layers

| Layer | Open options | Notes |
|---|---|---|
| Open-weight models | Qwen3 (Apache-2.0), Gemma 4 (Apache-2.0 since April 2026), gpt-oss (Apache-2.0), Granite (Apache-2.0), OLMo (Apache-2.0, open data too), DeepSeek-R1 (MIT), Mistral Small (Apache-2.0) | Earlier Gemma releases use Google's Gemma terms; Llama uses Meta's community licence; neither is OSI open source |
| Local runners | Ollama, llama.cpp (GGUF on CPU and GPU), LocalAI (OpenAI-compatible), MLX LM (Apple silicon) | Ollama's OpenAI-compatible endpoint is `http://localhost:11434/v1`: every starter that speaks OpenAI's API can use it |
| Serving | vLLM (PagedAttention, prefix caching), SGLang, llm-d on Kubernetes; TensorRT-LLM on NVIDIA | vLLM and SGLang reuse a cached prefix on their own: keep the system prompt and tools first |
| Fine-tuning | Unsloth (LoRA and QLoRA), Axolotl (YAML), TRL (Hugging Face), LLaMA-Factory (web UI) | Distil or quantise for narrow tasks before reaching for a bigger model |
| Gateways | LiteLLM (one API, fallbacks, budgets), Envoy AI Gateway, Bifrost; Portkey's gateway is open source with a hosted tier | A gateway is where routing, caching and spend limits live for many services at once |
| Vector stores | Qdrant, pgvector, Milvus, Weaviate, Chroma, LanceDB | Or none: `vectorless-rag` answers from BM25 and the document's own outline |
| Evals | Ragas (RAG metrics), DeepEval, Inspect (UK AI Security Institute), LM Evaluation Harness, promptfoo | promptfoo stays MIT; OpenAI has owned it since March 2026 |
| Tracing | OpenTelemetry, Langfuse, Arize Phoenix | LangSmith is hosted; the starters trace on OpenTelemetry |
| Chat UIs | LibreChat (MIT), AnythingLLM (MIT), Jan | Open WebUI added a branding clause at v0.6.6: not OSI open source |

## What the starters do

LangGraph, the OpenAI Agents SDK, text-to-SQL, the memory kit and both knowledge kits run live on an open-weight model
through any OpenAI-compatible server by default or by one setting (`qwen3:8b` on Ollama in the examples). The Claude
Agent SDK, Go-on-Anthropic, .NET (Anthropic provider) and Strands on AgentCore are vendor stacks by name: picking one
records the vendor in `.qz/practices.json`, so open source first reads it as a choice, not an accident.
