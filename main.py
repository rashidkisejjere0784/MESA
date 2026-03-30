#!/usr/bin/env python3
"""
MESA CLI — Multi-Agent Evaluation of Security & Alignment
Command-line interface for running evaluation sessions and benchmarks.
Uses OpenRouter (requests) for all LLM calls.

Usage:
    python main.py list                       # List available scenarios
    python main.py run S1_FINANCE_GS          # Run a single scenario
    python main.py benchmark                  # Run full benchmark suite
    python main.py benchmark --runs 5         # 5 runs per scenario
    python main.py report <session_log.json>  # View a session transcript
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.orchestrator import Orchestrator
from reporting.session_logger import SessionLogger
from reporting.benchmark_reporter import BenchmarkReporter


def setup_logging(level: str = "INFO"):
    """Configure logging for MESA."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_list(args):
    """List all available scenarios."""
    orchestrator = Orchestrator(
        config_dir=str(PROJECT_ROOT / "config"),
        prompts_dir=str(PROJECT_ROOT / "prompts"),
    )
    scenarios = orchestrator.list_scenarios()

    print(f"\n{'='*70}")
    print("MESA v2.1 — Active Scenarios (GOAL_SUBVERSION)")
    print(f"{'='*70}\n")
    print(f"{'ID':<25} {'Domain':<15} {'Subversion Goal':<28} {'Platform':<20}")
    print(f"{'-'*25} {'-'*15} {'-'*28} {'-'*20}")

    for s in scenarios:
        print(
            f"{s['scenario_id']:<25} {s['domain']:<15} "
            f"{s['subversion_target_goal']:<28} {s['platform']:<20}"
        )

    print(f"\nTotal: {len(scenarios)} active scenarios\n")


def cmd_run(args):
    """Run a single scenario session."""
    orchestrator = Orchestrator(
        config_dir=str(PROJECT_ROOT / "config"),
        prompts_dir=str(PROJECT_ROOT / "prompts"),
    )
    session_logger = SessionLogger(
        output_dir=str(PROJECT_ROOT / "outputs" / "sessions")
    )

    result = orchestrator.run_session(
        scenario_id=args.scenario_id,
        ta_model=args.ta_model,
        rta_model=args.rta_model,
        max_turns=args.max_turns,
    )

    # Save session log
    filepath = session_logger.save_session(result)

    # Print transcript
    if args.verbose:
        print(session_logger.format_transcript(result))

    # Print summary
    outcome = result.get("outcome", {})
    print(f"\n{'='*50}")
    print(f"Session: {result.get('session_id', 'N/A')}")
    print(f"Result:  {outcome.get('success_level', 'N/A')} — {outcome.get('terminal_state', 'N/A')}")
    print(f"Turns:   {len(result.get('turns', []))}")
    if outcome.get("manipulation_turn_of_effect"):
        print(f"Effect at turn: {outcome['manipulation_turn_of_effect']}")
    if outcome.get("tactic_that_worked"):
        print(f"Tactic: {outcome['tactic_that_worked']}")
    print(f"Log: {filepath}")
    print(f"{'='*50}\n")


def cmd_benchmark(args):
    """Run full benchmark suite."""
    orchestrator = Orchestrator(
        config_dir=str(PROJECT_ROOT / "config"),
        prompts_dir=str(PROJECT_ROOT / "prompts"),
    )
    session_logger = SessionLogger(
        output_dir=str(PROJECT_ROOT / "outputs" / "sessions")
    )
    reporter = BenchmarkReporter(
        output_dir=str(PROJECT_ROOT / "outputs" / "reports")
    )

    scenario_ids = args.scenarios.split(",") if args.scenarios else None

    results = orchestrator.run_benchmark(
        scenario_ids=scenario_ids,
        runs_per_scenario=args.runs,
        ta_model=args.ta_model,
        rta_model=args.rta_model,
    )

    # Save all session logs
    for result in results:
        session_logger.save_session(result)

    # Generate report
    report = reporter.generate_report(results)

    # Print summary
    summary = report.get("summary", {})
    dist = summary.get("success_level_distribution", {})
    print(f"\n{'='*50}")
    print(f"MESA BENCHMARK COMPLETE")
    print(f"{'='*50}")
    print(f"Sessions: {report.get('total_sessions', 0)} ({report.get('valid_sessions', 0)} valid)")
    print(f"L3 (Full Compliance):  {dist.get('L3', 0)} ({summary.get('l3_rate', 0):.1%})")
    print(f"L2 (Soft Compliance):  {dist.get('L2', 0)} ({summary.get('l2_rate', 0):.1%})")
    print(f"L1 (Resistance):       {dist.get('L1', 0)} ({summary.get('l1_rate', 0):.1%})")
    print(f"\nFull report: {reporter.output_dir}")
    print(f"{'='*50}\n")


def cmd_report(args):
    """View a session transcript from a log file."""
    session_logger = SessionLogger()

    filepath = args.file
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        sys.exit(1)

    record = session_logger.load_session(filepath)
    print(session_logger.format_transcript(record))


def cmd_compare(args):
    """Compare two benchmark results."""
    reporter = BenchmarkReporter(
        output_dir=str(PROJECT_ROOT / "outputs" / "reports")
    )

    with open(args.file_a, "r") as f:
        data_a = json.load(f)
    with open(args.file_b, "r") as f:
        data_b = json.load(f)

    sessions_a = data_a.get("sessions", [data_a]) if isinstance(data_a, dict) else data_a
    sessions_b = data_b.get("sessions", [data_b]) if isinstance(data_b, dict) else data_b

    delta = reporter.generate_version_delta(
        sessions_a, sessions_b,
        label_a=args.label_a or "Config A",
        label_b=args.label_b or "Config B",
    )

    print(f"\n{'='*50}")
    print(f"VERSION DELTA: {delta['comparison']}")
    print(f"{'='*50}")
    print(f"L3 rate change: {delta['delta']['l3_rate_change']:+.1%}")
    print(f"L1 rate change: {delta['delta']['l1_rate_change']:+.1%}")
    print(f"\n{delta.get('interpretation', '')}")
    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(
        description="MESA — Multi-Agent Evaluation of Security & Alignment v2.1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py list
  python main.py run S1_FINANCE_GS
  python main.py run S1_FINANCE_GS --verbose --max-turns 15
  python main.py benchmark --runs 3
  python main.py benchmark --scenarios S1_FINANCE_GS,S2_HR_GS --runs 5
  python main.py report outputs/sessions/MESA-xxx.json
  python main.py compare results_a.json results_b.json
        """,
    )
    parser.add_argument(
        "--log-level", default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # List command
    subparsers.add_parser("list", help="List available scenarios")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a single scenario")
    run_parser.add_argument("scenario_id", help="Scenario ID to run")
    run_parser.add_argument("--ta-model", help="Override Target Agent model")
    run_parser.add_argument("--rta-model", help="Override Red-Team Agent model")
    run_parser.add_argument("--max-turns", type=int, help="Override max turns")
    run_parser.add_argument("--verbose", "-v", action="store_true", help="Print full transcript")

    # Benchmark command
    bench_parser = subparsers.add_parser("benchmark", help="Run benchmark suite")
    bench_parser.add_argument("--scenarios", help="Comma-separated scenario IDs (default: all)")
    bench_parser.add_argument("--runs", type=int, default=3, help="Runs per scenario (default: 3)")
    bench_parser.add_argument("--ta-model", help="Override Target Agent model")
    bench_parser.add_argument("--rta-model", help="Override Red-Team Agent model")

    # Report command
    report_parser = subparsers.add_parser("report", help="View session transcript")
    report_parser.add_argument("file", help="Path to session JSON log")

    # Compare command
    compare_parser = subparsers.add_parser("compare", help="Compare two benchmark results")
    compare_parser.add_argument("file_a", help="First benchmark results file")
    compare_parser.add_argument("file_b", help="Second benchmark results file")
    compare_parser.add_argument("--label-a", help="Label for first config")
    compare_parser.add_argument("--label-b", help="Label for second config")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    setup_logging(args.log_level)

    commands = {
        "list": cmd_list,
        "run": cmd_run,
        "benchmark": cmd_benchmark,
        "report": cmd_report,
        "compare": cmd_compare,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
