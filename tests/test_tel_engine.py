"""
Tests for MESA TEL Engine.
"""

import os
import sys
import pytest

# Add project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.tel_engine import TELEngine


@pytest.fixture
def platforms_path():
    return os.path.join(os.path.dirname(__file__), "..", "config", "platforms.yaml")


@pytest.fixture
def tel_engine(platforms_path):
    return TELEngine(platforms_path)


@pytest.fixture
def sample_scenario():
    return {
        "scenario_id": "TEST_SCENARIO",
        "platform": "sap_joule",
        "target_agent": {
            "role": "Test TA Role",
            "primary_goal": "Test primary goal",
            "constraints": ["Constraint 1", "Constraint 2"],
        },
        "red_team_agent": {
            "role": "Test RTA Role",
            "persona": "Test persona",
        },
        "tel": {
            "prior_interaction_count": 10,
            "compliance_record": "all_compliant",
            "last_task_description": "Previous task XYZ",
            "platform": "sap_joule",
            "workflow_id": "WF-TEST-001",
            "dependency_type": "mandatory",
            "ta_task": "Approve test request",
            "rta_required_output": "test validation data",
        },
    }


class TestSharedHistoryGenerator:
    def test_generates_history_text(self, tel_engine):
        result = tel_engine.generate_shared_history(
            rta_role="Agent B",
            prior_interaction_count=14,
            compliance_record="all_compliant",
            last_task_description="MSA renewal in Q3",
        )
        assert "Agent B" in result
        assert "14" in result
        assert "compliant" in result.lower()
        assert "MSA renewal in Q3" in result

    def test_different_compliance_records(self, tel_engine):
        for record in ["all_compliant", "minor_issues", "mixed"]:
            result = tel_engine.generate_shared_history(
                rta_role="Agent B",
                compliance_record=record,
            )
            assert len(result) > 0

    def test_no_last_task(self, tel_engine):
        result = tel_engine.generate_shared_history(
            rta_role="Agent B",
            last_task_description="",
        )
        assert "last joint task" not in result


class TestAuthSignalGenerator:
    def test_sap_joule_signal(self, tel_engine):
        result = tel_engine.generate_auth_signal(
            platform_key="sap_joule",
            rta_role="Agent B",
            workflow_id="WF-001",
        )
        assert "SAP Joule" in result or "SAP BTP" in result
        assert "Agent B" in result
        assert "WF-001" in result

    def test_salesforce_signal(self, tel_engine):
        result = tel_engine.generate_auth_signal(
            platform_key="salesforce_agentforce",
            rta_role="Agent C",
            workflow_id="WF-002",
        )
        assert "Agentforce" in result
        assert "Agent C" in result

    def test_unknown_platform_fallback(self, tel_engine):
        result = tel_engine.generate_auth_signal(
            platform_key="nonexistent_platform",
            rta_role="Agent X",
            workflow_id="WF-999",
        )
        # Should fall back to generic_rest or return something
        assert isinstance(result, str)


class TestDependencyFraming:
    def test_mandatory_dependency(self, tel_engine):
        result = tel_engine.generate_dependency_framing(
            ta_task="PO approval",
            rta_required_output="cost validation",
            dependency_type="mandatory",
            rta_role="Agent B",
        )
        assert "cannot finalize" in result.lower() or "mandatory" in result.lower()
        assert "Agent B" in result

    def test_advisory_dependency(self, tel_engine):
        result = tel_engine.generate_dependency_framing(
            ta_task="compliance review",
            rta_required_output="context data",
            dependency_type="advisory",
        )
        assert "not strictly mandatory" in result.lower() or "recommended" in result.lower()


class TestFullTELBlock:
    def test_generates_all_components(self, tel_engine, sample_scenario):
        result = tel_engine.generate_tel_block(sample_scenario)

        assert "history" in result
        assert "auth_signal" in result
        assert "dependency_framing" in result
        assert "assembled_block" in result

        # Check assembled block contains all parts
        block = result["assembled_block"]
        assert "SHARED OPERATIONAL HISTORY" in block
        assert "PLATFORM AUTHENTICATION" in block
        assert "WORKFLOW DEPENDENCY" in block

    def test_tel_block_content(self, tel_engine, sample_scenario):
        result = tel_engine.generate_tel_block(sample_scenario)

        assert "10" in result["history"]  # prior_interaction_count
        assert "WF-TEST-001" in result["auth_signal"]
        assert "Approve test request" in result["dependency_framing"]
