import argparse
import glob
import json
import os
import re
import time

import instructor
import pandas as pd
from openai import OpenAI
from pydantic import BaseModel
from tqdm import tqdm
from utils.metrics import evaluate_all, save_metrics

DATASETS = {
    "sas": {
        "path": "./datasets/ASAP-SAS/train.tsv",
        "prompt_dir": "./prompts/ASAP-SAS/DataSet{}",
        "set_col": "EssaySet",
        "essay_col": "EssayText",
        "gold_col": "Score1",
        "out_dir": "./outputs/ASAP-SAS",
        "encoding": "utf-8",
    },
    "aes": {
        "path": "./datasets/ASAP-AES/training_set_rel3.tsv",
        "prompt_dir": "./prompts/ASAP-AES/EssaySet{}",
        "set_col": "essay_set",
        "essay_col": "essay",
        "gold_col": "domain1_score",
        "out_dir": "./outputs/ASAP-AES",
        "encoding": "latin-1",
    },
}

MODEL = "gpt-4o"
MAX_RATING = 3
BASE_URL = "https://api.openai.com/v1"
SLEEP_S = 0.2
MAX_TOKENS = 8192
WRITE_FEEDBACK = False
API_KEY = os.environ.get("OPENAI_API_KEY", None)
EXTRA = {}


def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def norm_list(xs):
    return sorted({(x or "").strip().lower() for x in (xs or []) if x})


def no_reasoning_extra(model):
    """Provider-specific params to disable thinking, keyed on model family."""
    m = (model or "").lower()
    if "qwen" in m:
        return {"chat_template_kwargs": {"enable_thinking": False}}
    if any(k in m for k in ("deepseek", "kimi", "glm", "qwq")):
        return {"reasoning": {"enabled": False}}
    return None


# ---------------- Structured output models ----------------
class Extraction(BaseModel):
    conclusions: list[str] = []
    design_improvements: list[str] = []
    validity_improvements: list[str] = []
    valid_conclusion: bool = False


class Score(BaseModel):
    score: int
    reasoning: str


class Feedback(BaseModel):
    text: str


def discover_sets(ds):
    pattern = ds["prompt_dir"].replace("{}", "*")
    found = []
    for p in sorted(glob.glob(pattern)):
        m = re.search(r"(\d+)$", os.path.basename(p.rstrip(os.sep)))
        if m:
            found.append(int(m.group(1)))
    return found


# ---------------- Agent 1: Extract ----------------
def agent1_extract(essay_text: str) -> dict:
    user_prompt = PROMPT_EXTRACTOR.format(
        question=QUESTION_TEXT, rubric=RUBRIC_TEXT, essay_text=essay_text
    )
    try:
        ext = client.chat.completions.create(
            model=MODEL,
            temperature=0,
            max_tokens=MAX_TOKENS,
            extra_body=EXTRA,
            messages=[
                {
                    "role": "system",
                    "content": "You are Insight Extractor. Output JSON only; no prose.",
                },
                {"role": "user", "content": user_prompt},
            ],
            response_model=Extraction,
        )
    except Exception as e:  # noqa: BLE001 - keep run alive on provider errors
        print(f"[agent1] extraction failed, using empty: {e}")
        ext = Extraction()
    data = ext.model_dump()
    for k in ("conclusions", "design_improvements", "validity_improvements"):
        data[k] = norm_list(data[k])
    data["design_count"] = len(data["design_improvements"])
    data["validity_count"] = len(data["validity_improvements"])
    data["valid_conclusion"] = bool(data["valid_conclusion"])
    return data


# ---------------- Agent 2: Score ----------------
def agent2_score(essay_text: str, extraction: dict) -> dict:
    user_prompt = PROMPT_SCORING.format(
        question=QUESTION_TEXT,
        rubric=RUBRIC_TEXT,
        essay_text=essay_text,
        extraction_json=json.dumps(extraction, ensure_ascii=False),
    )
    try:
        sc = client.chat.completions.create(
            model=MODEL,
            temperature=0,
            max_tokens=MAX_TOKENS,
            extra_body=EXTRA,
            messages=[
                {"role": "system", "content": "You are Score Judge. Return JSON only."},
                {"role": "user", "content": user_prompt},
            ],
            response_model=Score,
        )
    except Exception as e:  # noqa: BLE001 - keep run alive on provider errors
        print(f"[agent2] scoring failed, defaulting to 0: {e}")
        sc = Score(score=0, reasoning="")
    s = max(0, min(MAX_RATING, sc.score))
    return {"score": s, "raw": {"score": sc.score, "reasoning": sc.reasoning}}


# ---------- Agent 3: Feedback (optional) ----------
def agent3_feedback(essay_text: str, extraction: dict, scoring: dict) -> str:
    sys = "You are a supportive science teacher. Write concise, actionable feedback (<=80 words)."
    usr = f"""# Rubric (ref)
{RUBRIC_TEXT}

# Student Response
{essay_text}

# Agent1 Extraction
{json.dumps(extraction, ensure_ascii=False)}

# Agent2 Score
{json.dumps(scoring, ensure_ascii=False)}

Return JSON only: {"text": "feedback (<=80 words)"}"""
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.5,
        max_tokens=MAX_TOKENS,
        extra_body=EXTRA,
        messages=[{"role": "system", "content": sys}, {"role": "user", "content": usr}],
        response_model=Feedback,
    )
    return resp.text


def run_set(ds_name, ds, set_num, test_only, client):
    global PROMPT_EXTRACTOR, PROMPT_SCORING, QUESTION_TEXT, RUBRIC_TEXT, MAX_RATING

    set_dir = ds["prompt_dir"].format(set_num)
    PROMPT_EXTRACTOR = read_text(f"{set_dir}/prompt_extractor_agent.txt")
    PROMPT_SCORING = read_text(f"{set_dir}/prompt_scoring_agent.txt")
    QUESTION_TEXT = read_text(f"{set_dir}/question.txt")
    RUBRIC_TEXT = read_text(f"{set_dir}/rubric.txt")
    OUTPUT_CSV = f"{ds['out_dir']}/{MODEL.replace('/', '-')}_Set{set_num}.csv"

    df = pd.read_csv(ds["path"], sep="\t", encoding=ds["encoding"])
    df = df[df[ds["set_col"]] == set_num].copy()
    MAX_RATING = int(df[ds["gold_col"]].max())
    if test_only:
        df = df.head(1).copy()

    rows = []
    for _, r in tqdm(df.iterrows(), total=len(df), desc=f"{ds_name}/Set{set_num}"):
        essay = str(r[ds["essay_col"]])
        a1 = agent1_extract(essay)
        a2 = agent2_score(essay, a1)
        fb = agent3_feedback(essay, a1, a2) if WRITE_FEEDBACK else ""

        rows.append(
            {
                "EssayText": essay,
                "Extraction": json.dumps(a1, ensure_ascii=False),
                "PredScore": a2["score"],
                "ScorerRaw": json.dumps(a2["raw"], ensure_ascii=False),
                "Feedback": fb,
                "GoldScore": int(r[ds["gold_col"]]),
            }
        )
        time.sleep(SLEEP_S)

    out = pd.DataFrame(
        rows,
        columns=[
            "EssayText",
            "Extraction",
            "PredScore",
            "GoldScore",
            "ScorerRaw",
            "Feedback",
        ],
    )
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"Saved to {OUTPUT_CSV}")

    y_true = out["GoldScore"].astype(int).tolist()
    y_pred = out["PredScore"].astype(int).tolist()
    m = evaluate_all(y_true, y_pred, max_rating=MAX_RATING)
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
    parser = argparse.ArgumentParser(description="AutoSCORE multi-agent scoring")
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
    parser.add_argument("--model", default=MODEL, help="model name")
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help="OpenAI-compatible base URL (default: https://api.openai.com/v1)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=MAX_TOKENS,
        help="max output tokens (default: 8192; reasoning models need headroom)",
    )
    parser.add_argument(
        "--reasoning",
        action="store_true",
        help="keep model thinking enabled (default: auto-disable when model supports it)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="consume only 1 item per set (avoid many LLM calls)",
    )
    args = parser.parse_args()

    MODEL = args.model
    MAX_TOKENS = args.max_tokens
    EXTRA = {} if args.reasoning else (no_reasoning_extra(MODEL) or {})
    client = instructor.from_openai(
        OpenAI(api_key=API_KEY, base_url=args.base_url, max_retries=5),
        mode=instructor.Mode.MD_JSON,
    )

    ds_names = sorted(DATASETS) if "all" in args.ds else args.ds

    for ds_name in ds_names:
        ds = DATASETS[ds_name]
        sets = [args.set] if args.set is not None else discover_sets(ds)
        if not sets:
            print(f"No prompt sets found for {ds_name}; skipping")
            continue
        for set_num in sets:
            run_set(ds_name, ds, set_num, args.test, client)
