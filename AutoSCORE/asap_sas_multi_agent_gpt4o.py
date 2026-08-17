import argparse
import json
import os
import re
import time

import pandas as pd
from openai import OpenAI
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
    },
    "aes": {
        "path": "./datasets/ASAP-AES/training_set_rel3.tsv",
        "prompt_dir": "./prompts/ASAP-AES/EssaySet{}",
        "set_col": "essay_set",
        "essay_col": "essay",
        "gold_col": "domain1_score",
        "out_dir": "./outputs/ASAP-AES",
    },
}

MODEL = "gpt-4o"
MAX_RATING = 3
BASE_URL = "https://api.openai.com/v1"
TEST_ROWS = 5
SLEEP_S = 0.2
WRITE_FEEDBACK = False
API_KEY = os.environ.get("OPENAI_API_KEY", None)


def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def parse_json(text, default):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError, json.JSONDecodeError):
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        return json.loads(m.group(0)) if m else default


def norm_list(xs):
    return sorted({(x or "").strip().lower() for x in (xs or []) if x})


# ---------------- Provider-native structured output ----------------
# Fallback chain: json_schema -> json_object -> plain text.
# parse_json stays as final net: some models ignore response_format entirely.
EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "conclusions": {"type": "array", "items": {"type": "string"}},
        "design_improvements": {"type": "array", "items": {"type": "string"}},
        "validity_improvements": {"type": "array", "items": {"type": "string"}},
        "valid_conclusion": {"type": "boolean"},
    },
    "required": [
        "conclusions",
        "design_improvements",
        "validity_improvements",
        "valid_conclusion",
    ],
}

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "reasoning": {"type": "string"},
    },
    "required": ["score", "reasoning"],
}

def chat_json(messages, schema=None):
    """Native JSON mode when provider supports it; degrade gracefully."""
    if schema is not None:
        try:
            return client.chat.completions.create(
                model=MODEL,
                temperature=0,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "result", "schema": schema, "strict": True},
                },
            )
        except Exception:  # noqa: BLE001 - provider may not support json_schema
            pass  # fall through to json_object
    try:
        return client.chat.completions.create(
            model=MODEL,
            temperature=0,
            messages=messages,
            response_format={"type": "json_object"},
        )
    except Exception:  # noqa: BLE001 - provider may not support json_object either
        return client.chat.completions.create(
            model=MODEL, temperature=0, messages=messages
        )

# ---------------- Agent 1: Extract ----------------
def agent1_extract(essay_text: str) -> dict:
    user_prompt = PROMPT_EXTRACTOR.format(
        question=QUESTION_TEXT, rubric=RUBRIC_TEXT, essay_text=essay_text
    )
    # print("\n--- Prompt ---")
    # print(user_prompt)
    # print("--------------")
    resp = chat_json(
        [
            {
                "role": "system",
                "content": "You are Insight Extractor. Output JSON only; no prose.",
            },
            {"role": "user", "content": user_prompt},
        ],
        schema=EXTRACT_SCHEMA,
    )
    data = parse_json(resp.choices[0].message.content, {})
    if not isinstance(data, dict):
        data = {}
    data["conclusions"] = norm_list(data.get("conclusions"))
    data["design_improvements"] = norm_list(data.get("design_improvements"))
    data["validity_improvements"] = norm_list(data.get("validity_improvements"))
    data["design_count"] = len(data["design_improvements"])
    data["validity_count"] = len(data["validity_improvements"])
    data["valid_conclusion"] = bool(data.get("valid_conclusion"))
    return data


# ---------------- Agent 2: Score ----------------
def agent2_score(essay_text: str, extraction: dict) -> dict:
    user_prompt = PROMPT_SCORING.format(
        question=QUESTION_TEXT,
        rubric=RUBRIC_TEXT,
        essay_text=essay_text,
        extraction_json=json.dumps(extraction, ensure_ascii=False),
    )
    resp = chat_json(
        [
            {"role": "system", "content": "You are Score Judge. Return JSON only."},
            {"role": "user", "content": user_prompt},
        ],
        schema=SCORE_SCHEMA,
    )
    got = parse_json(resp.choices[0].message.content, {})
    if not isinstance(got, dict):
        got = {}
    try:
        s = int(got.get("score", 0))
    except (ValueError, TypeError):
        s = 0
    return {"score": max(0, min(MAX_RATING, s)), "raw": got}


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

Return only the feedback text (<=80 words)."""
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.5,
        messages=[{"role": "system", "content": sys}, {"role": "user", "content": usr}],
    )
    return (resp.choices[0].message.content or "").strip()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AutoSCORE multi-agent scoring")
    parser.add_argument("--ds", choices=sorted(DATASETS), default="sas", help="dataset: sas or aes (default: sas)")
    parser.add_argument(
        "--set", type=int, default=None, help="essay set number (default: 2 for sas, 1 for aes)"
    )
    parser.add_argument("--model", default=MODEL, help="model name (default: gpt-4o)")
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help="OpenAI-compatible base URL (default: https://api.openai.com/v1)",
    )
    args = parser.parse_args()
    MODEL = args.model
    ds = DATASETS[args.ds]
    if args.set is None:
        args.set = 2 if args.ds == "sas" else 1

    set_dir = ds["prompt_dir"].format(args.set)
    PROMPT_EXTRACTOR = read_text(f"{set_dir}/prompt_extractor_agent.txt")
    PROMPT_SCORING = read_text(f"{set_dir}/prompt_scoring_agent.txt")
    QUESTION_TEXT = read_text(f"{set_dir}/question.txt")
    RUBRIC_TEXT = read_text(f"{set_dir}/rubric.txt")
    OUTPUT_CSV = f"{ds['out_dir']}/{MODEL.replace('/', '-')}_Set{args.set}.csv"

    client = OpenAI(api_key=API_KEY, base_url=args.base_url)

    df = pd.read_csv(ds["path"], sep="\t")
    df = df[df[ds["set_col"]] == args.set].copy()
    MAX_RATING = int(df[ds["gold_col"]].max())
    if TEST_ROWS is not None:
        df = df.head(TEST_ROWS).copy()

    rows = []
    for _, r in tqdm(df.iterrows(), total=len(df), desc="Multi-agent"):
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
