.PHONY: run-multi test-multi

BASE_URL ?= https://api.together.ai/v1
MODEL ?= meta-llama/Llama-3.3-70B-Instruct-Turbo

run-multi:
	uv run --env-file .env asap_sas_multi_agent.py --base-url=$(BASE_URL) --model=$(MODEL) --ds=all

test-multi:
	uv run --env-file .env asap_sas_multi_agent.py --base-url=$(BASE_URL) --model=$(MODEL) --ds=all --test
