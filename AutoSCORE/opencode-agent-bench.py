import argparse
import json
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace

import pandas as pd
from asap_sas_multi_agent import DATASETS, discover_sets, read_text
from tqdm import tqdm
from utils.metrics import evaluate_all, save_metrics

MODEL = "gpt-4o"
WORKERS = 4
TIMEOUT_S = 300
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(PROJECT_DIR, "opencode.log")
LOG_LOCK = threading.Lock()


def build_prompt(question: str, rubric: str, essay: str) -> str:
    return f"""# Question
{question}

# Scoring Rubric
{rubric}

# Student Essay
{essay}"""


def parse_score(out: str):
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if m:
        try:
            return int(json.loads(m.group(0))["score"])
        except (ValueError, KeyError, TypeError):
            pass
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    if lines:
        m = re.search(r"(\d+)", lines[-1])
        if m:
            return int(m.group(1))
    m = re.search(r"(\d+)\s*$", out, re.MULTILINE)
    if m:
        return int(m.group(1))
    return None


def run_opencode(
    model: str, prompt: str, debug: bool = False, agent: str | None = None
):
    cmd = ["opencode", "run", "--model", model, "--auto", "--format", "json"]
    if agent:
        cmd += ["--agent", agent]
    cmd.append(prompt)
    if debug:
        cmd += ["--log-level", "DEBUG"]
    with open(LOG_FILE, "a", encoding="utf-8") as logf:
        with LOG_LOCK:
            logf.write(f"[opencode] cmd: {' '.join(cmd)}\n")
            logf.flush()

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=PROJECT_DIR,
            stdin=subprocess.DEVNULL,
            bufsize=1,
        )
        out_lines, err_lines = [], []

        def pump(stream, lines):
            for line in stream:
                lines.append(line)
                with LOG_LOCK:
                    logf.write(line)
                    logf.flush()

        t1 = threading.Thread(target=pump, args=(proc.stdout, out_lines))
        t2 = threading.Thread(target=pump, args=(proc.stderr, err_lines))
        t1.start()
        t2.start()
        try:
            proc.wait(timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            t1.join()
            t2.join()
            raise
        t1.join()
        t2.join()
        with LOG_LOCK:
            logf.write(f"[opencode] returncode: {proc.returncode}\n")
            logf.flush()
    return SimpleNamespace(
        returncode=proc.returncode,
        stdout="".join(out_lines),
        stderr="".join(err_lines),
    )


def extract_text(out: str) -> str:
    """Pull assistant text parts out of --format json event stream."""
    texts = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except ValueError:
            continue
        part = evt.get("part") or {}
        if evt.get("type") == "text" and part.get("type") == "text":
            texts.append(part.get("text", ""))
    return "\n".join(t for t in texts if t)


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
        proc1 = run_opencode(model, prompt, debug, agent="rubric-extractor")
    except subprocess.TimeoutExpired:
        print(f"[rubric-extractor] timed out after {TIMEOUT_S}s, defaulting to 0")
        return 0, "TIMEOUT"
    if proc1.returncode != 0:
        print(f"[rubric-extractor] exit {proc1.returncode}: {proc1.stderr.strip()}")
        return 0, extract_text(proc1.stdout)
    evidence = extract_text(proc1.stdout).strip()

    try:
        proc2 = run_opencode(
            model,
            f"{prompt}\n\n# Agent1 (rubric-extractor) evidence — may contain errors, verify against essay and rubric\n{evidence}",
            debug,
            agent="scorer",
        )
    except subprocess.TimeoutExpired:
        print(f"[scorer] timed out after {TIMEOUT_S}s, defaulting to 0")
        return 0, "TIMEOUT"
    raw = extract_text(proc2.stdout).strip()
    if proc2.returncode != 0:
        print(f"[scorer] exit {proc2.returncode}: {proc2.stderr.strip()}")
        return 0, raw
    s = parse_score(raw)
    if s is None:
        print("[scorer] no score parsed from output, defaulting to 0")
        return 0, raw
    return max(0, min(max_rating, s)), raw


def run_set(ds_name, ds, set_num, model, test_only, debug=False, workers=WORKERS):
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

    essays = [(str(r[ds["essay_col"]]), int(r[ds["gold_col"]])) for _, r in df.iterrows()]

    def score_one(item):
        essay, gold = item
        pred, raw = score_essay(model, question, rubric, essay, max_rating, debug)
        return {"EssayText": essay, "PredScore": pred, "RawOutput": raw, "GoldScore": gold}

    rows = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(score_one, item) for item in essays]
        for fut in tqdm(as_completed(futures), total=len(futures), desc=f"{ds_name}/Set{set_num}"):
            rows.append(fut.result())

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
    parser.add_argument(
        "--ds",
        nargs="+",
        choices=sorted(DATASETS) + ["all"],
        default=["all"],
        help="dataset(s) to run, or 'all' (default: all)",
    )
    parser.add_argument(
        "--set",
        type=int,
        default=None,
        help="essay set number (default: all sets in dataset)",
    )
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
    parser.add_argument(
        "--workers",
        type=int,
        default=WORKERS,
        help=f"parallel opencode processes (default: {WORKERS})",
    )
    args = parser.parse_args()

    test_only = args.test
    ds_names = sorted(DATASETS) if "all" in args.ds else args.ds
    for ds_name in ds_names:
        ds = DATASETS[ds_name]
        sets = [args.set] if args.set is not None else discover_sets(ds)
        if not sets:
            print(f"No prompt sets found for {ds_name}; skipping")
            continue
        for set_num in sets:
            run_set(
                ds_name, ds, set_num, args.model, test_only, args.debug, args.workers
            )
