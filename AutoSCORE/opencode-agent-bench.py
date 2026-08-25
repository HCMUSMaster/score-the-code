import argparse
import os
import re
import subprocess
import time

import pandas as pd
from asap_sas_multi_agent import DATASETS, discover_sets, read_text
from tqdm import tqdm
from utils.metrics import evaluate_all, save_metrics

MODEL = "gpt-4o"
SLEEP_S = 0.2
TIMEOUT_S = 300
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(PROJECT_DIR, "opencode.log")


def build_prompt(question: str, rubric: str, essay: str) -> str:
    return f"""Score this essay using the essay-scoring workflow: first run the rubric-extractor agent, then run the scorer agent. Do not score without running both.

# Question
{question}

# Scoring Rubric
{rubric}

# Student Essay
{essay}

Output ONLY the final score as a single integer, alone on the last line of your reply. Nothing else after it. No markdown, no explanation after the integer."""


def parse_score(out: str):
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    if lines:
        m = re.search(r"(\d+)", lines[-1])
        if m:
            return int(m.group(1))
    m = re.search(r"(\d+)\s*$", out, re.MULTILINE)
    if m:
        return int(m.group(1))
    return None


def run_opencode(model: str, prompt: str, debug: bool = False):
    cmd = ["opencode", "run", "--model", model, "--auto", prompt]
    if os.environ.get("OPENCODE_LOG", "1") == "1":
        cmd.append("--print-logs")
    if debug:
        cmd += ["--log-level", "DEBUG"]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_DIR,
        timeout=TIMEOUT_S,
    )
    if (os.environ.get("OPENCODE_LOG", "1") == "1" or debug) and proc.stderr:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[opencode] stderr:\n{proc.stderr}\n")
    return proc


def score_essay(
    model: str,
    question: str,
    rubric: str,
    essay: str,
    max_rating: int,
    debug: bool = False,
):
    prompt = build_prompt(question, rubric, essay)
    try:
        proc = run_opencode(model, prompt, debug)
    except subprocess.TimeoutExpired:
        print(f"[opencode] timed out after {TIMEOUT_S}s, defaulting to 0")
        return 0, "TIMEOUT"
    raw = proc.stdout.strip()
    if proc.returncode != 0:
        print(f"[opencode] exit {proc.returncode}: {proc.stderr.strip()}")
        return 0, raw
    s = parse_score(raw)
    if s is None:
        print("[opencode] no score parsed from output, defaulting to 0")
        return 0, raw
    return max(0, min(max_rating, s)), raw


def run_set(ds_name, ds, set_num, model, test_only, debug=False):
    set_dir = ds["prompt_dir"].format(set_num)
    question = read_text(f"{set_dir}/question.txt")
    rubric = read_text(f"{set_dir}/rubric.txt")
    out_dir = os.path.join(PROJECT_DIR, "outputs", "agent-bench", ds_name)
    OUTPUT_CSV = f"{out_dir}/{model.replace('/', '-')}_Set{set_num}.csv"

    df = pd.read_csv(ds["path"], sep="\t", encoding=ds["encoding"])
    df = df[df[ds["set_col"]] == set_num].copy()
    max_rating = int(df[ds["gold_col"]].max())
    if test_only:
        df = df.head(1).copy()

    rows = []
    for _, r in tqdm(df.iterrows(), total=len(df), desc=f"{ds_name}/Set{set_num}"):
        essay = str(r[ds["essay_col"]])
        pred, raw = score_essay(model, question, rubric, essay, max_rating, debug)
        rows.append(
            {
                "EssayText": essay,
                "PredScore": pred,
                "RawOutput": raw,
                "GoldScore": int(r[ds["gold_col"]]),
            }
        )
        time.sleep(SLEEP_S)

    if test_only:
        print("TEST MODE: not writing results to disk")
        return

    out = pd.DataFrame(
        rows, columns=["EssayText", "PredScore", "GoldScore", "RawOutput"]
    )
    os.makedirs(out_dir, exist_ok=True)
    out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"Saved to {OUTPUT_CSV}")

    y_true = out["GoldScore"].astype(int).tolist()
    y_pred = out["PredScore"].astype(int).tolist()
    m = evaluate_all(y_true, y_pred, max_rating=max_rating)
    print(f"Rows evaluated: {len(out)}")
    print(f"QWK:         {m['QWK']:.4f}")
    print(f"Pearson:     {m['Pearson']:.4f}")
    print(f"Spearman:    {m['Spearman']:.4f}")
    print(f"Accuracy:    {m['Accuracy']:.4f}")
    print(f"AdjAccuracy: {m['AdjAccuracy']:.4f}")
    print(f"MAE:         {m['MAE']:.4f}")
    print(f"CohenKappa:  {m['CohenKappa']:.4f}")

    metrics_path = OUTPUT_CSV.replace(".csv", "_metrics.json")
    save_metrics(metrics_path, m)
    print(f"Saved metrics to {metrics_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AutoSCORE via opencode agents")
    parser.add_argument("--model", default=MODEL, help="model name (provider/model)")
    parser.add_argument(
        "--test",
        action="store_true",
        help="consume only 1 item per set (avoid many opencode runs)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="pass --log-level DEBUG to opencode and print all stderr logs",
    )
    args = parser.parse_args()

    test_only = args.test
    for ds_name, ds in DATASETS.items():
        sets = discover_sets(ds)
        if not sets:
            print(f"No prompt sets found for {ds_name}; skipping")
            continue
        for set_num in sets:
            run_set(ds_name, ds, set_num, args.model, test_only, args.debug)
