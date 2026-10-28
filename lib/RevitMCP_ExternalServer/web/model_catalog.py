"""Curated tool-capable models, checked against provider catalogs on 2026-10-27.

OpenRouter IDs: https://openrouter.ai/api/v1/models
Direct IDs: https://developers.openai.com/api/docs/models
https://platform.claude.com/docs/en/models/overview
https://ai.google.dev/gemini-api/docs/models
https://docs.x.ai/developers/models/grok-4.7
"""


MODEL_CATALOG = [
    {"name": "GPT-6.1 Sol", "group": "OpenAI", "ids": {"openrouter": "openai/gpt-6.1-sol", "openai": "gpt-6.1-sol"}},
    {"name": "GPT-6.1 Terra", "group": "OpenAI", "ids": {"openrouter": "openai/gpt-6.1-terra", "openai": "gpt-6.1-terra"}},
    {"name": "GPT-6 Astra", "group": "OpenAI", "ids": {"openrouter": "openai/gpt-6-astra", "openai": "gpt-6-astra"}},
    {"name": "Claude Opus 5.5", "group": "Anthropic", "ids": {"openrouter": "anthropic/claude-opus-5.5", "anthropic": "claude-opus-5-5"}},
    {"name": "Claude Fable 5.1", "group": "Anthropic", "ids": {"openrouter": "anthropic/claude-fable-5.1", "anthropic": "claude-fable-5-1"}},
    {"name": "Claude Haiku 5.5", "group": "Anthropic", "ids": {"openrouter": "anthropic/claude-haiku-5.5", "anthropic": "claude-haiku-5-5"}},
    {"name": "Gemini 3.8 Flash", "group": "Google", "ids": {"openrouter": "google/gemini-3.8-flash", "google": "gemini-3.8-flash"}},
    {"name": "Gemini 4 Argon", "group": "Google", "ids": {"openrouter": "google/gemini-4-argon", "google": "gemini-4-argon"}},
    {"name": "Kimi K3.1 Pro", "group": "Open models", "ids": {"openrouter": "moonshotai/kimi-k3.1-pro"}},
    {"name": "GLM 5.3", "group": "Open models", "ids": {"openrouter": "z-ai/glm-5.3"}},
    {"name": "Grok 4.7", "group": "xAI", "ids": {"openrouter": "x-ai/grok-4.7", "xai": "grok-4.7"}},
]
