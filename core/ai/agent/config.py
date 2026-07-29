"""
Shared configuration for the AI agent package.

Single source of truth for the Ollama model name, so every submodule
that calls chat() uses the same value instead of each declaring (and
risking drifting on) its own constant.
"""

MODEL = "llama3.1"
