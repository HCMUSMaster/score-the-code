.PHONY: run-multi test-multi run-agent-bench test-agent-bench

BASE_URL ?= https://5e3c-34-48-41-101.ngrok-free.app/v1
MODEL ?= Qwen/Qwen2.5-7B-Instruct-AWQ

run-multi:
	uv run --env-file .env asap_sas_multi_agent.py --base-url=$(BASE_URL) --model=$(MODEL) --ds=all --workers 16

test-multi:
	uv run --env-file .env asap_sas_multi_agent.py --base-url=$(BASE_URL) --model=$(MODEL) --ds=all --test

run-agent-bench:
	uv run --env-file .env opencode-agent-bench.py --model=kaggle/$(MODEL)

test-agent-bench:
	uv run --env-file .env opencode-agent-bench.py --model=kaggle/$(MODEL) --test
