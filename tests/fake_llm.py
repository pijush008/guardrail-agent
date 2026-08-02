"""Re-export of the deterministic fake LLM for the test suite."""
from agent.fake_llm import FakeLLM, FakeUsage

__all__ = ["FakeLLM", "FakeUsage"]
