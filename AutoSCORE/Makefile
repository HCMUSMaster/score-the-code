.PHONY: run-multi test-multi

BASE_URL ?= https://api.together.ai/v1
MODEL ?= deepseek-ai/DeepSeek-V4-Flash-0731

run-multi:
	uv run --env-file .env asap_sas_multi_agent_gpt4o.py --base-url=$(BASE_URL) --model=$(MODEL) --ds=all

test-multi:
	uv run --env-file .env asap_sas_multi_agent_gpt4o.py --base-url=$(BASE_URL) --model=$(MODEL) --ds=all --test
