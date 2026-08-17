.PHONY: run-multi

# Run multi-agent GPT-4o scorer. Reads OPENAI_API_KEY from .env.
run-multi:
	uv run --env-file .env asap_sas_multi_agent_gpt4o.py --base-url=https://api.together.ai/v1 --model=Qwen/Qwen3.5-9B --set=2
