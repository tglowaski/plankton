"""Tests for benchmark.swebench.gate module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def _make_task_result(
    task_id="repo__1",
    *,
    baseline_patch="diff --git a/f.py\n-old\n+new",
    plankton_patch="diff --git a/f.py\n-old\n+better",
    baseline_error_type=None,
    plankton_error_type=None,
    baseline_error=None,
    plankton_error=None,
    baseline_passed=None,
    plankton_passed=None,
    plankton_claude_output=None,
    plankton_stderr="",
    baseline_elapsed=30.0,
    plankton_elapsed=90.0,
):
    """Return a run_task-compatible dict for testing."""
    baseline_meta: dict = {"elapsed_s": baseline_elapsed}
    if baseline_error_type is not None:
        baseline_meta["error_type"] = baseline_error_type
    if baseline_error is not None:
        baseline_meta["error"] = baseline_error

    plankton_meta: dict = {"elapsed_s": plankton_elapsed, "stderr": plankton_stderr}
    if plankton_error_type is not None:
        plankton_meta["error_type"] = plankton_error_type
    if plankton_error is not None:
        plankton_meta["error"] = plankton_error
    if plankton_claude_output is not None:
        plankton_meta["claude_output"] = plankton_claude_output

    return {
        "task_id": task_id,
        "conditions": {
            "baseline": {
                "patch": baseline_patch,
                "passed": baseline_passed,
                "metadata": baseline_meta,
            },
            "plankton": {
                "patch": plankton_patch,
                "passed": plankton_passed,
                "metadata": plankton_meta,
            },
        },
    }


def _make_config(tmp_path: Path):
    """Return a GateConfig for testing."""
    from benchmark.swebench.gate import GateConfig

    return GateConfig(
        seed=42,
        model="test",
        timeout=60,
        results_dir=tmp_path / "r",
        patches_dir=tmp_path / "p",
    )


# ── Criterion 1: check_no_crash_or_timeout ───────────────────────────


class TestCheckNoCrashOrTimeout:
    """Test criterion 1: no infra errors or timeouts."""

    def test_passes_when_no_errors(self) -> None:
        """Pass when no infra errors or timeouts exist."""
        from benchmark.swebench.gate import check_no_crash_or_timeout

        result = check_no_crash_or_timeout([_make_task_result()])
        assert result.passed is True

    def test_fails_on_infra_error(self) -> None:
        """Fail when an infra error is present."""
        from benchmark.swebench.gate import check_no_crash_or_timeout

        result = check_no_crash_or_timeout([_make_task_result(baseline_error_type="infra")])
        assert result.passed is False

    def test_fails_on_timeout(self) -> None:
        """Fail when a timeout error is present."""
        from benchmark.swebench.gate import check_no_crash_or_timeout

        result = check_no_crash_or_timeout([_make_task_result(plankton_error="timeout")])
        assert result.passed is False


# ── Criterion 2: check_patches_nonempty ──────────────────────────────


class TestCheckPatchesNonempty:
    """Test criterion 2: all patches are non-empty strings."""

    def test_passes_when_all_nonempty(self) -> None:
        """Pass when all patches are non-empty."""
        from benchmark.swebench.gate import check_patches_nonempty

        result = check_patches_nonempty([_make_task_result()])
        assert result.passed is True

    def test_fails_when_baseline_empty(self) -> None:
        """Fail when baseline patch is empty."""
        from benchmark.swebench.gate import check_patches_nonempty

        result = check_patches_nonempty([_make_task_result(baseline_patch="")])
        assert result.passed is False

    def test_fails_when_plankton_empty(self) -> None:
        """Fail when plankton patch is empty."""
        from benchmark.swebench.gate import check_patches_nonempty

        result = check_patches_nonempty([_make_task_result(plankton_patch="")])
        assert result.passed is False


# ── Criterion 3: check_hook_activity ─────────────────────────────────


class TestCheckHookActivity:
    """Test criterion 3: plankton condition shows hook evidence."""

    def test_passes_when_posttooluse_in_output(self) -> None:
        """Pass when PostToolUse appears in claude output."""
        from benchmark.swebench.gate import check_hook_activity

        result = check_hook_activity([_make_task_result(plankton_claude_output="some PostToolUse event")])
        assert result.passed is True

    def test_passes_when_hook_in_stderr(self) -> None:
        """Pass when hook keyword appears in stderr."""
        from benchmark.swebench.gate import check_hook_activity

        result = check_hook_activity([_make_task_result(plankton_stderr="running hook check")])
        assert result.passed is True

    def test_passes_when_Hook_uppercase_in_stderr(self) -> None:
        """Pass when Hook (capitalized) appears in stderr."""
        from benchmark.swebench.gate import check_hook_activity

        result = check_hook_activity([_make_task_result(plankton_stderr="Running Hook check")])
        assert result.passed is True

    def test_passes_when_LINTER_uppercase_in_stderr(self) -> None:
        """Pass when LINTER (uppercase) appears in stderr."""
        from benchmark.swebench.gate import check_hook_activity

        result = check_hook_activity([_make_task_result(plankton_stderr="LINTER running")])
        assert result.passed is True

    def test_fails_when_no_evidence(self) -> None:
        """Fail when no hook evidence is found."""
        from benchmark.swebench.gate import check_hook_activity

        result = check_hook_activity(
            [_make_task_result(plankton_claude_output="nothing relevant", plankton_stderr="clean")]
        )
        assert result.passed is False

    def test_cannot_verify_when_no_output(self) -> None:
        """Fail with cannot-verify message when no output is available."""
        from benchmark.swebench.gate import check_hook_activity

        result = check_hook_activity([_make_task_result()])
        assert result.passed is False
        assert "cannot verify" in result.detail.lower()


# ── Criterion 4: check_eval_harness_verdicts ─────────────────────────


class TestCheckEvalHarnessVerdicts:
    """Test criterion 4: all passed fields are non-None."""

    def test_deferred_when_all_none(self) -> None:
        """Fail as deferred when all passed fields are None."""
        from benchmark.swebench.gate import check_eval_harness_verdicts

        result = check_eval_harness_verdicts([_make_task_result()])
        assert result.passed is False
        assert "deferred" in result.detail.lower()

    def test_passes_when_all_populated(self) -> None:
        """Pass when all passed fields are populated."""
        from benchmark.swebench.gate import check_eval_harness_verdicts

        result = check_eval_harness_verdicts([_make_task_result(baseline_passed=True, plankton_passed=False)])
        assert result.passed is True

    def test_fails_partial_when_some_passed_none(self) -> None:
        """Fail when some passed fields are None (not all verdicts returned)."""
        from benchmark.swebench.gate import check_eval_harness_verdicts

        result = check_eval_harness_verdicts([_make_task_result(baseline_passed=True, plankton_passed=None)])
        assert result.passed is False


# ── Criterion 5: check_patches_differ ────────────────────────────────


class TestCheckPatchesDiffer:
    """Test criterion 5: at least one task has different patches."""

    def test_passes_when_different(self) -> None:
        """Pass when baseline and plankton patches differ."""
        from benchmark.swebench.gate import check_patches_differ

        result = check_patches_differ([_make_task_result()])
        assert result.passed is True

    def test_fails_when_identical(self) -> None:
        """Fail when all patches are identical."""
        from benchmark.swebench.gate import check_patches_differ

        result = check_patches_differ([_make_task_result(baseline_patch="same", plankton_patch="same")])
        assert result.passed is False


# ── Criterion 6: check_cost_and_time ─────────────────────────────────


class TestCheckCostAndTime:
    """Test criterion 6: wall time and cost within ranges."""

    def test_passes_within_range(self) -> None:
        """Pass when wall time is within allowed range."""
        from benchmark.swebench.gate import check_cost_and_time

        result = check_cost_and_time([_make_task_result()], wall_time_s=600.0)
        assert result.passed is True

    def test_fails_exceeds_max_wall(self) -> None:
        """Fail when wall time exceeds maximum."""
        from benchmark.swebench.gate import check_cost_and_time

        result = check_cost_and_time([_make_task_result()], wall_time_s=8000.0, max_wall_s=7200.0)
        assert result.passed is False

    def test_passes_no_cost_data(self) -> None:
        """Pass when no cost data is available."""
        from benchmark.swebench.gate import check_cost_and_time

        result = check_cost_and_time([_make_task_result()], wall_time_s=100.0)
        assert result.passed is True


# ── run_gate ─────────────────────────────────────────────────────────


class TestRunGate:
    """Test run_gate orchestration."""

    def _good_run_task_fn(self, task, **kwargs):
        """Return a passing task result for the given task."""
        return _make_task_result(
            task_id=task["instance_id"],
            plankton_claude_output="PostToolUse event",
            baseline_passed=True,
            plankton_passed=True,
        )

    def test_run_gate_raises_on_empty_tasks(self, tmp_path: Path) -> None:
        """Raise ValueError when tasks list is empty."""
        from benchmark.swebench.gate import run_gate

        config = _make_config(tmp_path)
        with __import__("pytest").raises(ValueError, match="empty"):
            run_gate([], config)

    def test_calls_run_task_for_each(self, tmp_path: Path) -> None:
        """Call run_task_fn once per task."""
        from benchmark.swebench.gate import run_gate

        mock_fn = MagicMock(side_effect=self._good_run_task_fn)
        tasks = [{"instance_id": f"t_{i}"} for i in range(2)]
        config = _make_config(tmp_path)
        run_gate(tasks, config, run_task_fn=mock_fn)
        assert mock_fn.call_count == 2

    def test_passes_when_all_criteria_pass(self, tmp_path: Path) -> None:
        """Pass when all gate criteria are satisfied."""
        from benchmark.swebench.gate import run_gate

        tasks = [{"instance_id": f"t_{i}"} for i in range(2)]
        config = _make_config(tmp_path)
        result = run_gate(tasks, config, run_task_fn=MagicMock(side_effect=self._good_run_task_fn))
        assert result.passed is True

    def test_fails_when_one_criterion_fails(self, tmp_path: Path) -> None:
        """Fail when any single criterion is not met."""
        from benchmark.swebench.gate import run_gate

        def bad_fn(task, **kwargs):
            return _make_task_result(task_id=task["instance_id"], baseline_patch="")

        tasks = [{"instance_id": "t_0"}]
        config = _make_config(tmp_path)
        result = run_gate(tasks, config, run_task_fn=bad_fn)
        assert result.passed is False

    def test_has_6_criteria(self, tmp_path: Path) -> None:
        """Return exactly 6 criteria in the gate result."""
        from benchmark.swebench.gate import run_gate

        tasks = [{"instance_id": "t_0"}]
        config = _make_config(tmp_path)
        result = run_gate(tasks, config, run_task_fn=MagicMock(side_effect=self._good_run_task_fn))
        assert len(result.criteria) == 6


# ── format_gate_report ───────────────────────────────────────────────


class TestFormatGateReport:
    """Test format_gate_report output."""

    def _make_gate_result(self, passed=True, criteria=None):
        """Return a GateResult for testing."""
        from benchmark.swebench.gate import CriterionResult, GateResult

        if criteria is None:
            criteria = [
                CriterionResult(name="c1", passed=True, detail="ok"),
                CriterionResult(name="c2", passed=True, detail="ok"),
            ]
        return GateResult(
            passed=passed,
            criteria=criteria,
            tasks_run=2,
            wall_time_s=120.0,
            results_dir=Path("/tmp/results"),
        )

    def test_includes_pass_fail_header(self) -> None:
        """Include PASS or FAIL in the report header."""
        from benchmark.swebench.gate import format_gate_report

        report = format_gate_report(self._make_gate_result(passed=True))
        assert "PASS" in report

        report = format_gate_report(self._make_gate_result(passed=False))
        assert "FAIL" in report

    def test_includes_all_criterion_names(self) -> None:
        """Include all criterion names in the report."""
        from benchmark.swebench.gate import format_gate_report

        report = format_gate_report(self._make_gate_result())
        assert "c1" in report
        assert "c2" in report

    def test_shows_detail_for_failed(self) -> None:
        """Show detail text for failed criteria."""
        from benchmark.swebench.gate import CriterionResult, format_gate_report

        result = self._make_gate_result(
            passed=False,
            criteria=[
                CriterionResult(name="c1", passed=True, detail="ok"),
                CriterionResult(name="c2", passed=False, detail="broken thing"),
            ],
        )
        report = format_gate_report(result)
        assert "broken thing" in report
