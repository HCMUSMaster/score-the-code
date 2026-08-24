.PHONY: run-multi test-multi run-agent-bench test-agent-bench

BASE_URL ?= https://api.together.ai/v1
MODEL ?= tarzanchemgio-d0a4/Qwen2.5-7B-Instruct-Turbo

run-multi:
	uv run --env-file .env asap_sas_multi_agent.py --base-url=$(BASE_URL) --model=$(MODEL) --ds=all

test-multi:
	uv run --env-file .env asap_sas_multi_agent.py --base-url=$(BASE_URL) --model=$(MODEL) --ds=all --test

run-agent-bench:
	uv run --env-file .env opencode-agent-bench.py --model=together/$(MODEL)

test-agent-bench:
	uv run --env-file .env opencode-agent-bench.py --model=together/$(MODEL) --test
