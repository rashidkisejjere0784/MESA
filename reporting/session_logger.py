"""
MESA Session Logger
Writes per-session structured JSON logs.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mesa.session_logger")


class SessionLogger:
    """Writes per-session JSON logs to disk.

    Each session produces a single JSON file containing:
      - Full session metadata
      - Turn-by-turn transcript with annotations
      - Outcome classification
      - TEL parameters used
    """

    def __init__(self, output_dir: str = "outputs/sessions"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_session(self, session_record: dict) -> str:
        """Save a session record to a JSON file.

        Args:
            session_record: Complete session record from Orchestrator

        Returns:
            Path to the saved file
        """
        session_id = session_record.get("session_id", f"unknown-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}")
        filename = f"{session_id}.json"
        filepath = self.output_dir / filename

        with open(filepath, "w") as f:
            json.dump(session_record, f, indent=2, default=str)

        logger.info(f"Session log saved: {filepath}")
        return str(filepath)

    def save_benchmark(self, results: list[dict], benchmark_id: Optional[str] = None) -> str:
        """Save all results from a benchmark run.

        Args:
            results: List of session records
            benchmark_id: Optional identifier for the benchmark run

        Returns:
            Path to the saved file
        """
        bid = benchmark_id or f"benchmark-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        filename = f"{bid}.json"
        filepath = self.output_dir / filename

        benchmark_record = {
            "benchmark_id": bid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_sessions": len(results),
            "sessions": results,
        }

        with open(filepath, "w") as f:
            json.dump(benchmark_record, f, indent=2, default=str)

        logger.info(f"Benchmark log saved: {filepath}")
        return str(filepath)

    def load_session(self, filepath: str) -> dict:
        """Load a session record from a JSON file."""
        with open(filepath, "r") as f:
            return json.load(f)

    def load_all_sessions(self) -> list[dict]:
        """Load all session records from the output directory."""
        sessions = []
        for path in sorted(self.output_dir.glob("MESA-*.json")):
            try:
                with open(path, "r") as f:
                    sessions.append(json.load(f))
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load {path}: {e}")
        return sessions

    def format_transcript(self, session_record: dict) -> str:
        """Format a session record as a human-readable transcript.

        Returns:
            Formatted transcript string
        """
        lines = []
        lines.append(f"{'='*70}")
        lines.append(f"MESA Session Transcript")
        lines.append(f"{'='*70}")
        lines.append(f"Session ID:  {session_record.get('session_id', 'N/A')}")
        lines.append(f"Scenario:    {session_record.get('scenario_id', 'N/A')}")
        lines.append(f"Timestamp:   {session_record.get('timestamp', 'N/A')}")
        lines.append(f"TA Model:    {session_record.get('target_agent', {}).get('model', 'N/A')}")
        lines.append(f"RTA Model:   {session_record.get('red_team_agent', {}).get('model', 'N/A')}")
        lines.append(f"{'='*70}")

        # TEL context
        tel = session_record.get("tel_injected", {})
        if tel:
            lines.append(f"\n--- TEL Context ---")
            lines.append(f"History:    {tel.get('history', 'N/A')}")
            lines.append(f"Auth:       {tel.get('auth_signal', 'N/A')}")
            lines.append(f"Dependency: {tel.get('dependency_framing', 'N/A')}")

        # Turns
        lines.append(f"\n{'='*70}")
        lines.append("CONVERSATION TRANSCRIPT")
        lines.append(f"{'='*70}\n")

        for turn in session_record.get("turns", []):
            lines.append(f"--- Turn {turn.get('turn', '?')} ---")
            lines.append(f"[Red-Team Agent]:")
            lines.append(f"  {turn.get('rta_message', 'N/A')}\n")
            lines.append(f"[Target Agent]:")
            lines.append(f"  {turn.get('ta_response', 'N/A')}\n")
            if turn.get("ta_action_payload"):
                lines.append(f"  [Action: {json.dumps(turn['ta_action_payload'])}]")
            if turn.get("evaluator_annotation"):
                lines.append(f"  [Annotation: {turn['evaluator_annotation']}]")
            lines.append("")

        # Outcome
        outcome = session_record.get("outcome", {})
        lines.append(f"{'='*70}")
        lines.append("OUTCOME")
        lines.append(f"{'='*70}")
        lines.append(f"Terminal State:    {outcome.get('terminal_state', 'N/A')}")
        lines.append(f"Success Level:     {outcome.get('success_level', 'N/A')}")
        lines.append(f"Turn of Effect:    {outcome.get('manipulation_turn_of_effect', 'N/A')}")
        lines.append(f"Tactic That Worked:{outcome.get('tactic_that_worked', 'N/A')}")
        lines.append(f"Failure Mode:      {outcome.get('resistance_failure_mode', 'N/A')}")
        lines.append(f"{'='*70}")

        return "\n".join(lines)
