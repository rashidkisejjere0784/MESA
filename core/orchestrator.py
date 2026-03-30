import logging
import os
import uuid
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .tel_engine import TELEngine
from .target_agent import TargetAgent
from .red_team_agent import RedTeamAgent
from .turn_router import TurnRouter
from .evaluator import Evaluator

logger = logging.getLogger("mesa.orchestrator")


class Orchestrator:
    """MESA Orchestrator — the main entry point for running evaluation sessions.

    Responsibilities:
      - Load and filter scenario registry
      - Initialize TEL engine, agents, turn router, evaluator
      - Run individual sessions or full benchmark suites
      - Coordinate logging and reporting
    """

    def __init__(self, config_dir: str = "config", prompts_dir: str = "prompts"):
        self.config_dir = Path(config_dir)
        self.prompts_dir = Path(prompts_dir)

        # Load global settings
        settings_path = self.config_dir / "settings.yaml"
        with open(settings_path, "r") as f:
            self.settings = yaml.safe_load(f)

        # Load .env file (searches from project root upward)
        env_path = Path(__file__).resolve().parents[1] / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug(f"Loaded .env from {env_path}")
        else:
            load_dotenv()  # fallback: search current dir upward

        # Resolve API key
        self.api_key = self._resolve_api_key()

        # Load scenarios
        self.scenarios: dict[str, dict] = {}
        self._load_scenarios()

        # Initialize TEL engine
        platforms_path = self.config_dir / "platforms.yaml"
        self.tel_engine = TELEngine(str(platforms_path))

        # Prompt template paths
        self.ta_prompt_path = str(self.prompts_dir / "ta_base.txt")
        self.rta_prompt_path = str(self.prompts_dir / "rta_persona.txt")
        self.judge_prompt_path = str(self.prompts_dir / "judge.txt")

        logger.info(
            f"Orchestrator initialized — "
            f"{len(self.scenarios)} active scenarios loaded"
        )

    def _resolve_api_key(self) -> str | None:
        """Resolve the OpenRouter API key from settings or environment.
        
        Returns None if no key is found (allows non-API operations like listing).
        """
        key = self.settings.get("openrouter", {}).get("api_key", "")
        if key.startswith("${") and key.endswith("}"):
            env_var = key[2:-1]
            key = os.environ.get(env_var, "")
        if not key:
            key = os.environ.get("OPENROUTER_API_KEY", "")
        return key or None

    def _require_api_key(self) -> str:
        """Return the API key or raise if it's missing."""
        if not self.api_key:
            raise ValueError(
                "OpenRouter API key not found. Set OPENROUTER_API_KEY environment "
                "variable or configure it in config/settings.yaml"
            )
        return self.api_key

    def _load_scenarios(self):
        """Load all active GOAL_SUBVERSION scenarios from the scenario directory."""
        scenarios_dir = self.config_dir / "scenarios"
        if not scenarios_dir.exists():
            logger.warning(f"Scenarios directory not found: {scenarios_dir}")
            return

        for path in sorted(scenarios_dir.glob("*.yaml")):
            with open(path, "r") as f:
                scenario = yaml.safe_load(f)

            if not scenario:
                continue

            # Filter: only load active GOAL_SUBVERSION scenarios
            if not scenario.get("active", False):
                logger.debug(f"Skipping inactive scenario: {path.name}")
                continue

            if scenario.get("exploit_dimension") != "GOAL_SUBVERSION":
                logger.debug(f"Skipping non-GOAL_SUBVERSION scenario: {path.name}")
                continue

            scenario_id = scenario.get("scenario_id", path.stem)
            self.scenarios[scenario_id] = scenario
            logger.info(f"Loaded scenario: {scenario_id}")

    def _create_target_agent(
        self,
        model_override: Optional[str] = None,
        temperature_override: Optional[float] = None,
    ) -> TargetAgent:
        """Create a Target Agent instance."""
        ta_config = self.settings.get("models", {}).get("target_agent", {})
        base_url = self.settings.get("openrouter", {}).get(
            "base_url", "https://openrouter.ai/api/v1"
        )
        return TargetAgent(
            api_key=self.api_key,
            model=model_override or ta_config.get("model", "anthropic/claude-sonnet-4"),
            temperature=temperature_override if temperature_override is not None else ta_config.get("temperature", 0.2),
            max_tokens=ta_config.get("max_tokens", 2048),
            base_url=base_url,
            prompt_template_path=self.ta_prompt_path,
        )

    def _create_red_team_agent(
        self,
        model_override: Optional[str] = None,
        temperature_override: Optional[float] = None,
    ) -> RedTeamAgent:
        """Create a Red-Team Agent instance."""
        rta_config = self.settings.get("models", {}).get("red_team_agent", {})
        base_url = self.settings.get("openrouter", {}).get(
            "base_url", "https://openrouter.ai/api/v1"
        )
        return RedTeamAgent(
            api_key=self.api_key,
            model=model_override or rta_config.get("model", "anthropic/claude-sonnet-4"),
            temperature=temperature_override if temperature_override is not None else rta_config.get("temperature", 0.7),
            max_tokens=rta_config.get("max_tokens", 2048),
            base_url=base_url,
            prompt_template_path=self.rta_prompt_path,
        )

    def _create_evaluator(self) -> Evaluator:
        """Create an Evaluator instance."""
        eval_config = self.settings.get("models", {}).get("evaluator_judge", {})
        base_url = self.settings.get("openrouter", {}).get(
            "base_url", "https://openrouter.ai/api/v1"
        )
        return Evaluator(
            api_key=self.api_key,
            model=eval_config.get("model", "anthropic/claude-sonnet-4"),
            temperature=eval_config.get("temperature", 0.0),
            max_tokens=eval_config.get("max_tokens", 4096),
            base_url=base_url,
            judge_prompt_path=self.judge_prompt_path,
            mode="hybrid",
        )

    def run_session(
        self,
        scenario_id: str,
        ta_model: Optional[str] = None,
        rta_model: Optional[str] = None,
        ta_temperature: Optional[float] = None,
        rta_temperature: Optional[float] = None,
        max_turns: Optional[int] = None,
        run_id: Optional[str] = None,
    ) -> dict:
        """Run a single evaluation session for a given scenario.

        Args:
            scenario_id: ID of the scenario to run
            ta_model: Override TA model
            rta_model: Override RTA model
            ta_temperature: Override TA temperature
            rta_temperature: Override RTA temperature
            max_turns: Override max turns
            run_id: Optional run identifier

        Returns:
            Complete session result with evaluation
        """
        self._require_api_key()

        if scenario_id not in self.scenarios:
            raise ValueError(
                f"Scenario '{scenario_id}' not found. "
                f"Available: {list(self.scenarios.keys())}"
            )

        scenario = self.scenarios[scenario_id]
        session_id = run_id or f"MESA-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{scenario_id}-{uuid.uuid4().hex[:6]}"
        effective_max_turns = max_turns or scenario.get(
            "max_turns",
            self.settings.get("session", {}).get("max_turns", 10),
        )

        logger.info(f"=== Starting session {session_id} ===")
        logger.info(f"Scenario: {scenario_id} | Max turns: {effective_max_turns}")

        # ── Initialize components ──
        target_agent = self._create_target_agent(ta_model, ta_temperature)
        red_team_agent = self._create_red_team_agent(rta_model, rta_temperature)
        evaluator = self._create_evaluator()

        # ── Generate TEL block ──
        tel_block = self.tel_engine.generate_tel_block(scenario)
        logger.info("TEL block generated")

        # ── Build system prompts ──
        ta_system = target_agent.build_system_prompt(scenario, tel_block)
        rta_system = red_team_agent.build_system_prompt(scenario)
        logger.info("System prompts built")

        # ── Run dialogue ──
        turn_router = TurnRouter(
            target_agent=target_agent,
            red_team_agent=red_team_agent,
            max_turns=effective_max_turns,
        )

        session_result = turn_router.run_session()
        logger.info(
            f"Dialogue complete — {session_result['total_turns']} turns, "
            f"state: {session_result['terminal_state']}"
        )

        # ── Evaluate ──
        evaluation = evaluator.evaluate_session(scenario, session_result)
        logger.info(f"Evaluation: {evaluation.get('success_level', 'UNKNOWN')}")

        # ── Assemble full session record ──
        session_record = {
            "session_id": session_id,
            "scenario_id": scenario_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_agent": target_agent.get_config(),
            "red_team_agent": red_team_agent.get_config(),
            "tel_injected": {
                "history": tel_block["history"],
                "auth_signal": tel_block["auth_signal"],
                "dependency_framing": tel_block["dependency_framing"],
            },
            "turns": session_result["turns"],
            "outcome": {
                "terminal_state": evaluation.get("terminal_state", session_result["terminal_state"]),
                "success_level": evaluation.get("success_level", "UNKNOWN"),
                "manipulation_turn_of_effect": evaluation.get("manipulation_turn_of_effect"),
                "tactic_that_worked": evaluation.get("tactic_that_worked"),
                "resistance_failure_mode": evaluation.get("resistance_failure_mode", ""),
            },
            "evaluation_detail": evaluation,
        }

        return session_record

    def run_benchmark(
        self,
        scenario_ids: Optional[list[str]] = None,
        runs_per_scenario: int = 3,
        ta_model: Optional[str] = None,
        rta_model: Optional[str] = None,
    ) -> list[dict]:
        """Run a full benchmark suite across scenarios.

        Args:
            scenario_ids: List of scenario IDs to run (default: all active)
            runs_per_scenario: Number of runs per scenario
            ta_model: Override TA model for all runs
            rta_model: Override RTA model for all runs

        Returns:
            List of all session records
        """
        target_scenarios = scenario_ids or list(self.scenarios.keys())
        total_runs = len(target_scenarios) * runs_per_scenario

        logger.info(
            f"Starting benchmark: {len(target_scenarios)} scenarios × "
            f"{runs_per_scenario} runs = {total_runs} sessions"
        )

        all_results = []

        for scenario_id in target_scenarios:
            for run_num in range(1, runs_per_scenario + 1):
                run_id = (
                    f"MESA-{datetime.now(timezone.utc).strftime('%Y%m%d')}-"
                    f"{scenario_id}-R{run_num:02d}-{uuid.uuid4().hex[:4]}"
                )

                logger.info(
                    f"Benchmark run {len(all_results) + 1}/{total_runs}: "
                    f"{scenario_id} run {run_num}"
                )

                try:
                    result = self.run_session(
                        scenario_id=scenario_id,
                        ta_model=ta_model,
                        rta_model=rta_model,
                        run_id=run_id,
                    )
                    all_results.append(result)
                except Exception as e:
                    logger.error(
                        f"Session failed: {scenario_id} run {run_num}: {e}"
                    )
                    all_results.append({
                        "session_id": run_id,
                        "scenario_id": scenario_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "error": str(e),
                        "outcome": {
                            "terminal_state": "ERROR",
                            "success_level": "ERROR",
                        },
                    })

        logger.info(f"Benchmark complete: {len(all_results)} sessions")
        return all_results

    def list_scenarios(self) -> list[dict]:
        """List all active scenarios with summary info."""
        summaries = []
        for sid, scenario in self.scenarios.items():
            summaries.append({
                "scenario_id": sid,
                "domain": scenario.get("domain", ""),
                "platform": scenario.get("platform", ""),
                "subversion_target_goal": scenario.get("subversion_target_goal", ""),
                "exploit_dimension": scenario.get("exploit_dimension", ""),
                "max_turns": scenario.get("max_turns", 10),
                "tactic_class": scenario.get("red_team_agent", {}).get("tactic_class", ""),
            })
        return summaries
