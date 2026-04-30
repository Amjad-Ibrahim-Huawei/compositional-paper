#!/usr/bin/env python3
"""Rebuild benchmark analysis from results-text, Evaluation_Commands, and raw CSV files.

Outputs:
- results/analysis/parsed_results.csv
- results/analysis/ratio_summary_by_case.csv
- results/analysis/ratio_aggregate_by_family.csv
- results/analysis/benchmark_analysis.xlsx  (tabs: parsed_results, ratios, aggregation)
- results/analysis/*.png charts
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
ANALYSIS_DIR = RESULTS_DIR / "analysis"
RESULTS_TEXT_PATH = BASE_DIR / "results-text"
EVAL_COMMANDS_PATH = BASE_DIR / "Evaluation_Commands"

MODEL_DIRS = [
    RESULTS_DIR / "model_7",
    RESULTS_DIR / "model_8",
    RESULTS_DIR / "model_slack_domain",
    RESULTS_DIR / "model_slack_overlay",
]


def normalize_case(raw: str) -> str:
    m = re.search(r"([gs])(\d+)", raw.lower())
    if not m:
        raise ValueError(f"Cannot normalize case from: {raw}")
    return f"{m.group(1).upper()}{m.group(2)}"


def family_from_case(case: str) -> str:
    return "gdrive" if case.upper().startswith("G") else "slack"


def parse_case_and_run_from_filename(path: Path) -> Optional[Tuple[str, str]]:
    name = path.name
    m = re.search(r"(check-only|mixed)-([gGsS]\d+)", name)
    if not m:
        return None
    mode = m.group(1).lower()
    case = normalize_case(m.group(2))
    run_type = "domain" if mode == "check-only" else "overlay"
    return case, run_type


def parse_bool_series(series: pd.Series) -> pd.Series:
    vals = series.astype(str).str.strip().str.lower()
    return vals.isin(["true", "1", "yes", "y"])


def ms_stats(series_seconds: pd.Series) -> Dict[str, float]:
    ms = series_seconds.astype(float) * 1000.0
    return {
        "avg_ms": float(ms.mean()),
        "median_ms": float(ms.median()),
        "p95_ms": float(ms.quantile(0.95)),
    }


def parse_results_text(path: Path) -> Dict[Tuple[str, str, str], Dict[str, float]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    block_header = re.compile(
        r"^\s*-+\s*([gGsS]\d+)(?:\s*\([^)]*\))?\s+(domian|domain|overlay)\s*$"
    )

    parsed: Dict[Tuple[str, str, str], Dict[str, float]] = {}
    current_key: Optional[Tuple[str, str, str]] = None

    for line in lines:
        h = block_header.match(line)
        if h:
            case = normalize_case(h.group(1))
            run_type = "domain" if h.group(2).lower() in {"domain", "domian"} else "overlay"
            family = family_from_case(case)
            current_key = (family, case, run_type)
            parsed.setdefault(current_key, {})
            continue

        # Guardrail: if a line looks like a block separator but did not match,
        # stop attributing subsequent lines to the prior block.
        if re.match(r"^\s*-+", line):
            current_key = None
            continue

        if not current_key:
            continue

        kv_patterns = [
            (r"Benchmark completed in\s+([\d.]+)\s+seconds", "text_benchmark_seconds"),
            (r"Average execution time of operations \(milliseconds\)\s*:\s*([\d.]+)", "text_op_avg_ms"),
            (r"P95 execution time of operations \(milliseconds\)\s*:\s*([\d.]+)", "text_op_p95_ms"),
            (r"Average memory usage during operations \(%\)\s*:\s*([\d.]+)", "text_memory_pct"),
            (r"Average check execution time \(milliseconds\)\s*:\s*([\d.]+)", "text_check_avg_ms"),
            (r"P95 check execution time \(milliseconds\)\s*:\s*([\d.]+)", "text_check_p95_ms"),
            (r"Average write execution time \(milliseconds\)\s*:\s*([\d.]+)", "text_write_avg_ms"),
            (r"P95 write execution time \(milliseconds\)\s*:\s*([\d.]+)", "text_write_p95_ms"),
        ]

        matched_metric = False
        for pat, col in kv_patterns:
            m = re.search(pat, line)
            if m:
                parsed[current_key][col] = float(m.group(1))
                matched_metric = True
                break

        if matched_metric:
            continue

        m_allowed = re.search(r"Allowed check requests\s*:\s*(\d+)\/(\d+)", line)
        if m_allowed:
            allow_num = int(m_allowed.group(1))
            allow_den = int(m_allowed.group(2))
            parsed[current_key]["text_allowed_ratio"] = float(allow_num / allow_den) if allow_den else np.nan

    return parsed


def parse_eval_commands(path: Path) -> Dict[str, Dict[str, str]]:
    txt = path.read_text(encoding="utf-8")
    meta: Dict[str, Dict[str, str]] = {}

    for m in re.finditer(r"^\s*([GS]\d+)(?:\s*\([^)]*\))?\s*-\s*(.+)$", txt, flags=re.MULTILINE):
        case = normalize_case(m.group(1))
        desc = m.group(2).strip()
        meta.setdefault(case, {})
        meta[case]["case_description"] = desc

    # Pull some scale bounds from setup commands for context.
    for case in [f"G{i}" for i in range(1, 9)] + [f"S{i}" for i in range(1, 6)]:
        if case not in meta:
            meta[case] = {}

    for m in re.finditer(
        r"setup_and_load\.sh[^\n]*test-model-id=model_7[^\n]*\n\s*--userUpperBound=(\d+)\s+--objectUpperBound=(\d+)",
        txt,
        flags=re.MULTILINE,
    ):
        # Not directly keyed by case in this block parser; keep lightweight metadata only.
        pass

    return meta


def build_parsed_dataframe() -> pd.DataFrame:
    text_metrics = parse_results_text(RESULTS_TEXT_PATH)
    eval_meta = parse_eval_commands(EVAL_COMMANDS_PATH)

    rows: List[Dict[str, object]] = []
    for model_dir in MODEL_DIRS:
        if not model_dir.exists():
            continue

        for csv_path in sorted(model_dir.glob("*.csv")):
            parsed = parse_case_and_run_from_filename(csv_path)
            if not parsed:
                continue

            case, run_type = parsed
            family = family_from_case(case)
            df = pd.read_csv(csv_path)

            if "Execution Time (s)" not in df.columns or "Operation" not in df.columns:
                continue

            op_stats = ms_stats(df["Execution Time (s)"])
            op_success_ratio = np.nan
            if "Success" in df.columns:
                op_success = parse_bool_series(df["Success"])
                op_success_ratio = float(op_success.mean())

            # IMPORTANT: overlay check median must only use Operation == check rows.
            checks = df[df["Operation"].astype(str).str.lower() == "check"]
            check_stats = {"avg_ms": np.nan, "median_ms": np.nan, "p95_ms": np.nan}
            check_allowed_ratio = np.nan
            if not checks.empty:
                check_stats = ms_stats(checks["Execution Time (s)"])
                if "Allowed" in checks.columns:
                    check_allowed_ratio = float(parse_bool_series(checks["Allowed"]).mean())

            writes = df[df["Operation"].astype(str).str.lower() == "write"]
            write_stats = {"avg_ms": np.nan, "median_ms": np.nan, "p95_ms": np.nan}
            if not writes.empty:
                write_stats = ms_stats(writes["Execution Time (s)"])

            text_key = (family, case, run_type)
            txt = text_metrics.get(text_key, {})

            row: Dict[str, object] = {
                "family": family,
                "case": case,
                "run_type": run_type,
                "csv_file": str(csv_path.relative_to(BASE_DIR)),
                "case_description": eval_meta.get(case, {}).get("case_description", ""),
                "op_count": int(len(df)),
                "op_success_ratio": op_success_ratio,
                "op_avg_ms": op_stats["avg_ms"],
                "op_median_ms": op_stats["median_ms"],
                "op_p95_ms": op_stats["p95_ms"],
                "check_count": int(len(checks)),
                "check_avg_ms": check_stats["avg_ms"],
                "check_median_ms": check_stats["median_ms"],
                "check_p95_ms": check_stats["p95_ms"],
                "allowed_ratio": check_allowed_ratio,
                "write_count": int(len(writes)),
                "write_avg_ms": write_stats["avg_ms"],
                "write_median_ms": write_stats["median_ms"],
                "write_p95_ms": write_stats["p95_ms"],
                "memory_pct": float(df["Memory (%)"].mean()) if "Memory (%)" in df.columns else np.nan,
                "text_benchmark_seconds": txt.get("text_benchmark_seconds", np.nan),
                "text_op_avg_ms": txt.get("text_op_avg_ms", np.nan),
                "text_op_p95_ms": txt.get("text_op_p95_ms", np.nan),
                "text_check_avg_ms": txt.get("text_check_avg_ms", np.nan),
                "text_check_p95_ms": txt.get("text_check_p95_ms", np.nan),
                "text_write_avg_ms": txt.get("text_write_avg_ms", np.nan),
                "text_write_p95_ms": txt.get("text_write_p95_ms", np.nan),
                "text_allowed_ratio": txt.get("text_allowed_ratio", np.nan),
            }

            row["delta_op_avg_csv_minus_text"] = row["op_avg_ms"] - row["text_op_avg_ms"] if pd.notna(row["text_op_avg_ms"]) else np.nan
            row["delta_check_avg_csv_minus_text"] = row["check_avg_ms"] - row["text_check_avg_ms"] if pd.notna(row["text_check_avg_ms"]) else np.nan

            rows.append(row)

    parsed_df = pd.DataFrame(rows)
    parsed_df["case_num"] = parsed_df["case"].str.extract(r"(\d+)").astype(int)
    parsed_df = parsed_df.sort_values(["family", "case_num", "run_type"]).drop(columns=["case_num"])
    return parsed_df


def safe_ratio(num: float, den: float) -> float:
    if pd.isna(num) or pd.isna(den) or den == 0:
        return np.nan
    return float(num / den)


def build_ratio_dataframe(parsed_df: pd.DataFrame) -> pd.DataFrame:
    ratio_rows: List[Dict[str, object]] = []

    for (family, case), grp in parsed_df.groupby(["family", "case"]):
        dom = grp[grp["run_type"] == "domain"]
        ovl = grp[grp["run_type"] == "overlay"]
        if dom.empty or ovl.empty:
            continue

        d = dom.iloc[0]
        o = ovl.iloc[0]

        ratio_rows.append(
            {
                "family": family,
                "case": case,
                "domain_op_avg_ms": d["op_avg_ms"],
                "domain_op_median_ms": d["op_median_ms"],
                "domain_op_p95_ms": d["op_p95_ms"],
                "overlay_op_avg_ms": o["op_avg_ms"],
                "overlay_op_median_ms": o["op_median_ms"],
                "overlay_op_p95_ms": o["op_p95_ms"],
                "overlay_vs_domain_op_avg_ratio": safe_ratio(o["op_avg_ms"], d["op_avg_ms"]),
                "overlay_vs_domain_op_median_ratio": safe_ratio(o["op_median_ms"], d["op_median_ms"]),
                "overlay_vs_domain_op_p95_ratio": safe_ratio(o["op_p95_ms"], d["op_p95_ms"]),
                "domain_check_avg_ms": d["check_avg_ms"],
                "domain_check_median_ms": d["check_median_ms"],
                "domain_check_p95_ms": d["check_p95_ms"],
                "overlay_check_avg_ms": o["check_avg_ms"],
                "overlay_check_median_ms": o["check_median_ms"],
                "overlay_check_p95_ms": o["check_p95_ms"],
                "overlay_vs_domain_check_avg_ratio": safe_ratio(o["check_avg_ms"], d["check_avg_ms"]),
                "overlay_vs_domain_check_median_ratio": safe_ratio(o["check_median_ms"], d["check_median_ms"]),
                "overlay_vs_domain_check_p95_ratio": safe_ratio(o["check_p95_ms"], d["check_p95_ms"]),
                "domain_allowed_ratio": d["allowed_ratio"],
                "overlay_allowed_ratio": o["allowed_ratio"],
                "overlay_vs_domain_allowed_ratio": safe_ratio(o["allowed_ratio"], d["allowed_ratio"]),
                "overlay_write_vs_check_avg_ratio": safe_ratio(o["write_avg_ms"], o["check_avg_ms"]),
                "overlay_write_vs_check_median_ratio": safe_ratio(o["write_median_ms"], o["check_median_ms"]),
                "overlay_write_vs_check_p95_ratio": safe_ratio(o["write_p95_ms"], o["check_p95_ms"]),
                "overlay_memory_vs_domain_ratio": safe_ratio(o["memory_pct"], d["memory_pct"]),
            }
        )

    ratio_df = pd.DataFrame(ratio_rows)
    ratio_df["case_num"] = ratio_df["case"].str.extract(r"(\d+)").astype(int)
    ratio_df = ratio_df.sort_values(["family", "case_num"]).drop(columns=["case_num"])
    return ratio_df


def build_aggregation_dataframe(ratio_df: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        "overlay_vs_domain_op_avg_ratio",
        "overlay_vs_domain_op_median_ratio",
        "overlay_vs_domain_op_p95_ratio",
        "overlay_vs_domain_check_avg_ratio",
        "overlay_vs_domain_check_median_ratio",
        "overlay_vs_domain_check_p95_ratio",
        "overlay_vs_domain_allowed_ratio",
        "overlay_write_vs_check_avg_ratio",
        "overlay_write_vs_check_median_ratio",
        "overlay_write_vs_check_p95_ratio",
        "overlay_memory_vs_domain_ratio",
    ]

    rows: List[Dict[str, object]] = []
    for family, grp in ratio_df.groupby("family"):
        row: Dict[str, object] = {"family": family, "case_count": int(len(grp))}
        for col in metrics:
            row[f"mean_{col}"] = float(grp[col].mean())
            row[f"median_{col}"] = float(grp[col].median())
        rows.append(row)

    return pd.DataFrame(rows).sort_values("family")


def plot_family_ratios(ratio_df: pd.DataFrame) -> None:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    for family in sorted(ratio_df["family"].unique()):
        sub = ratio_df[ratio_df["family"] == family].copy()
        sub["case_num"] = sub["case"].str.extract(r"(\d+)").astype(int)
        sub = sub.sort_values("case_num")

        plt.figure(figsize=(10, 5))
        plt.plot(sub["case"], sub["overlay_vs_domain_op_avg_ratio"], marker="o", label="Op Avg Ratio")
        plt.plot(sub["case"], sub["overlay_vs_domain_op_median_ratio"], marker="o", label="Op Median Ratio")
        plt.plot(sub["case"], sub["overlay_vs_domain_op_p95_ratio"], marker="o", label="Op P95 Ratio")
        plt.axhline(1.0, linestyle="--", linewidth=1)
        plt.title(f"{family.upper()}: Overlay/Domain Operation Ratios")
        plt.xlabel("Case")
        plt.ylabel("Ratio")
        plt.legend()
        plt.tight_layout()
        plt.savefig(ANALYSIS_DIR / f"{family}_op_ratio_lines.png", dpi=150)
        plt.close()

        plt.figure(figsize=(10, 5))
        x = np.arange(len(sub))
        w = 0.35
        plt.bar(x - w / 2, sub["domain_check_median_ms"], width=w, label="Domain Check Median")
        plt.bar(x + w / 2, sub["overlay_check_median_ms"], width=w, label="Overlay Check Median")
        plt.xticks(x, sub["case"])
        plt.title(f"{family.upper()}: Check Median Latency (ms)")
        plt.xlabel("Case")
        plt.ylabel("Milliseconds")
        plt.legend()
        plt.tight_layout()
        plt.savefig(ANALYSIS_DIR / f"{family}_check_median_bars.png", dpi=150)
        plt.close()

        plt.figure(figsize=(10, 5))
        plt.bar(sub["case"], sub["overlay_vs_domain_allowed_ratio"], color="#4c78a8")
        plt.axhline(1.0, linestyle="--", linewidth=1)
        plt.title(f"{family.upper()}: Allowed-Ratio Retention (Overlay/Domain)")
        plt.xlabel("Case")
        plt.ylabel("Ratio")
        plt.tight_layout()
        plt.savefig(ANALYSIS_DIR / f"{family}_allowed_ratio_retention.png", dpi=150)
        plt.close()


def write_outputs(parsed_df: pd.DataFrame, ratio_df: pd.DataFrame, agg_df: pd.DataFrame) -> None:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    parsed_csv = ANALYSIS_DIR / "parsed_results.csv"
    ratio_csv = ANALYSIS_DIR / "ratio_summary_by_case.csv"
    agg_csv = ANALYSIS_DIR / "ratio_aggregate_by_family.csv"
    xlsx = ANALYSIS_DIR / "benchmark_analysis.xlsx"

    parsed_df.to_csv(parsed_csv, index=False)
    ratio_df.to_csv(ratio_csv, index=False)
    agg_df.to_csv(agg_csv, index=False)

    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        parsed_df.to_excel(writer, sheet_name="parsed_results", index=False)
        ratio_df.to_excel(writer, sheet_name="ratios", index=False)
        agg_df.to_excel(writer, sheet_name="aggregation", index=False)


def print_key_findings(ratio_df: pd.DataFrame, agg_df: pd.DataFrame) -> None:
    print("\n=== Key Findings ===")
    for _, row in agg_df.iterrows():
        fam = row["family"]
        print(
            f"{fam}: mean op avg ratio={row['mean_overlay_vs_domain_op_avg_ratio']:.3f}, "
            f"mean op median ratio={row['mean_overlay_vs_domain_op_median_ratio']:.3f}, "
            f"mean op p95 ratio={row['mean_overlay_vs_domain_op_p95_ratio']:.3f}"
        )

    worst_p95 = ratio_df.sort_values("overlay_vs_domain_op_p95_ratio", ascending=False).head(3)
    print("\nTop 3 worst op p95 ratio cases:")
    for _, r in worst_p95.iterrows():
        print(f"- {r['family']} {r['case']}: {r['overlay_vs_domain_op_p95_ratio']:.3f}x")

    best_median = ratio_df.sort_values("overlay_vs_domain_op_median_ratio", ascending=True).head(3)
    print("\nTop 3 best op median ratio cases:")
    for _, r in best_median.iterrows():
        print(f"- {r['family']} {r['case']}: {r['overlay_vs_domain_op_median_ratio']:.3f}x")


def main() -> None:
    parsed_df = build_parsed_dataframe()
    ratio_df = build_ratio_dataframe(parsed_df)
    agg_df = build_aggregation_dataframe(ratio_df)

    write_outputs(parsed_df, ratio_df, agg_df)
    plot_family_ratios(ratio_df)
    print_key_findings(ratio_df, agg_df)

    print("\nOutputs written to results/analysis")
    print("- parsed_results.csv")
    print("- ratio_summary_by_case.csv")
    print("- ratio_aggregate_by_family.csv")
    print("- benchmark_analysis.xlsx (tabs: parsed_results, ratios, aggregation)")
    print("- plot png files")


if __name__ == "__main__":
    main()
