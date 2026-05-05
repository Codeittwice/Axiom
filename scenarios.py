"""
AXIOM Scenario Engine — executes multi-step workflows defined in config.yaml.

A scenario is a named ordered list of steps. Each step has an `action` key plus
parameters specific to that action. Steps support variable substitution from a
context dict (e.g. {project_name}, {date}, {time}).

See AXIOM_development_plan.md §4 for the full specification.

Wire-up (done in voice_assistant.py):
    from scenarios import ScenarioEngine
    engine = ScenarioEngine(
        config        = CFG,
        speak_fn      = speak,
        emit_fn       = _send,
        tool_executor = execute_tool,
        record_fn     = record_audio,
        transcribe_fn = transcribe,
    )

Then `engine.run("coding_sequence", {"project_name": "axiom"})` executes it.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Callable, Optional

log = logging.getLogger("axiom.scenarios")


class ScenarioEngine:
    """
    Executes scenarios from config["scenarios"]. Each scenario is a dict with:
      description (str)
      requires_project (bool, optional)
      steps (list of step dicts)

    Each step dict has an `action` key. Supported actions:
      speak         — text
      open_app      — app
      open_website  — target
      open_repo     — repo
      run_git       — command, [repo]
      run_terminal  — command, [repo], [wait_for_exit]
      tool          — name, inputs (dict)
      wait          — seconds
      ask           — prompt, slot
      branch        — if, then (list), else (list)
      notify        — title, message
    """

    def __init__(
        self,
        config: dict,
        speak_fn: Callable[[str], None],
        emit_fn: Callable[[str, dict], None],
        tool_executor: Callable[[str, dict], str],
        record_fn: Optional[Callable[[], Optional[str]]] = None,
        transcribe_fn: Optional[Callable[[str], str]] = None,
        project_registry: Any = None,
    ) -> None:
        self.config           = config
        self.scenarios        = config.get("scenarios", {}) or {}
        self.speak            = speak_fn
        self.emit             = emit_fn
        self.execute_tool     = tool_executor
        self.record           = record_fn
        self.transcribe       = transcribe_fn
        self.project_registry = project_registry

    # ─── Public API ─────────────────────────────────────────────────────────

    def list_scenarios(self) -> list[str]:
        return list(self.scenarios.keys())

    def get_scenario(self, name: str) -> Optional[dict]:
        return self.scenarios.get(self._normalize(name))

    def run(self, name: str, context: Optional[dict] = None) -> str:
        """
        Run a scenario by name.

        Returns a short summary string suitable for Gemini to include in its
        response. Step-level errors are caught and logged; the scenario
        continues to the next step on failure.
        """
        scenario = self.get_scenario(name)
        if scenario is None:
            available = ", ".join(self.scenarios.keys()) or "none configured"
            return f"Scenario '{name}' not found. Available: {available}"

        ctx   = self._build_context(context or {})
        steps = scenario.get("steps", []) or []

        # Backwards-compat: old format had `tabs:` instead of `steps:`
        if not steps and "tabs" in scenario:
            steps = [{"action": "open_website", "target": t} for t in scenario["tabs"]]

        total = len(steps)
        if total == 0:
            return f"Scenario '{name}' has no steps."

        log.info(f"Running scenario '{name}' with {total} steps. Context: {ctx}")

        succeeded = 0
        failed    = 0

        for i, step in enumerate(steps):
            action = step.get("action", "<missing>")
            self.emit("scenario_step", {
                "scenario": name,
                "step":     action,
                "index":    i,
                "total":    total,
            })
            try:
                result = self._execute_step(step, ctx)
                if result:
                    log.info(f"  step {i+1}/{total} [{action}] → {str(result)[:120]}")
                succeeded += 1
            except Exception as e:
                log.error(f"  step {i+1}/{total} [{action}] FAILED: {e}")
                self.emit("log", {"level": "error",
                                  "text": f"Scenario step {action} failed: {e}"})
                failed += 1
                # continue to next step — never break the scenario

        summary = f"Scenario '{name}' done ({succeeded}/{total} steps OK)"
        if failed:
            summary += f", {failed} failed"
        log.info(summary)
        return summary

    # ─── Context & substitution ─────────────────────────────────────────────

    def _build_context(self, base: dict) -> dict:
        """Merge built-in context vars with user-supplied ones."""
        now = datetime.now()
        ctx: dict = {
            "date":      now.strftime("%Y-%m-%d"),
            "time":      now.strftime("%H:%M"),
            "day":       now.strftime("%A"),
            "user_name": (self.config.get("assistant", {}) or {}).get("user_name", ""),
        }
        ctx.update(base)

        # Resolve project information if a project_name was supplied.
        # Prefer ProjectRegistry (Phase 2). Fall back to legacy lookup.
        if base.get("project_name"):
            project = self._resolve_project(base["project_name"])
            if project:
                if self.project_registry is not None:
                    ctx.update(self.project_registry.context_for(project))
                else:
                    ctx["project_name"]        = project.get("name", base["project_name"])
                    ctx["project_path"]        = project.get("repo_path", "")
                    ctx["project_description"] = project.get("description", "")
        return ctx

    def _resolve_project(self, name: str) -> Optional[dict]:
        """Look up a project via the registry (preferred) or legacy fallback."""
        if self.project_registry is not None:
            return self.project_registry.resolve(name)

        # Legacy fallback (no registry wired)
        projects = self.config.get("projects", {}) or {}
        repos    = self.config.get("repos", {}) or {}
        key      = self._normalize(name)

        if key in projects:
            p = dict(projects[key])
            p.setdefault("name", name)
            return p
        if key in repos:
            return {"name": name, "repo_path": repos[key]}
        return None

    @staticmethod
    def _normalize(s: str) -> str:
        return s.lower().strip().replace(" ", "_")

    def _substitute(self, text: Any, context: dict) -> Any:
        """
        Recursive {var} substitution. Strings get their {placeholders} replaced;
        dicts and lists are walked; other types pass through unchanged.
        """
        if isinstance(text, str):
            for key, value in context.items():
                text = text.replace(f"{{{key}}}", str(value))
            return text
        if isinstance(text, dict):
            return {k: self._substitute(v, context) for k, v in text.items()}
        if isinstance(text, list):
            return [self._substitute(v, context) for v in text]
        return text

    # ─── Step execution ─────────────────────────────────────────────────────

    def _execute_step(self, step: dict, context: dict) -> str:
        action = step.get("action", "")

        # ── speak ────────────────────────────────────────────────────────────
        if action == "speak":
            text = self._substitute(step.get("text", ""), context)
            self.speak(text)
            return text

        # ── open_app ─────────────────────────────────────────────────────────
        if action == "open_app":
            app = self._substitute(step["app"], context)
            return self.execute_tool("open_application", {"app_name": app})

        # ── open_website ─────────────────────────────────────────────────────
        if action == "open_website":
            target = self._substitute(step["target"], context)
            return self.execute_tool("open_website", {"target": target})

        # ── open_repo ────────────────────────────────────────────────────────
        if action == "open_repo":
            repo = self._substitute(step["repo"], context)
            return self.execute_tool("open_repo", {"repo_name": repo})

        # ── run_git ──────────────────────────────────────────────────────────
        if action == "run_git":
            command = self._substitute(step["command"], context)
            repo    = self._substitute(step.get("repo", ""), context)
            return self.execute_tool("run_git",
                                     {"command": command, "repo_name": repo})

        # ── run_terminal ─────────────────────────────────────────────────────
        if action == "run_terminal":
            command = self._substitute(step["command"], context)
            repo    = self._substitute(step.get("repo", ""), context)
            return self.execute_tool("run_terminal",
                                     {"command": command, "repo_name": repo})

        # ── tool (generic dispatch) ──────────────────────────────────────────
        if action == "tool":
            name   = step["name"]
            inputs = self._substitute(step.get("inputs", {}) or {}, context)
            return self.execute_tool(name, inputs)

        # ── wait ─────────────────────────────────────────────────────────────
        if action == "wait":
            seconds = float(step.get("seconds", 1))
            time.sleep(seconds)
            return f"waited {seconds}s"

        # ── ask (prompt user, fill slot) ─────────────────────────────────────
        if action == "ask":
            prompt = self._substitute(step["prompt"], context)
            slot   = step["slot"]
            self.speak(prompt)
            if not (self.record and self.transcribe):
                log.warning("ask action requires record_fn + transcribe_fn")
                context[slot] = ""
                return f"slot {slot} skipped (no recorder)"
            audio = self.record()
            if not audio:
                context[slot] = ""
                return f"slot {slot} empty (no audio)"
            answer = self.transcribe(audio) or ""
            context[slot] = answer
            return f"slot {slot} = {answer[:60]}"

        # ── branch (conditional) ─────────────────────────────────────────────
        if action == "branch":
            condition = self._substitute(step.get("if", ""), context)
            taken     = "then" if self._evaluate(condition) else "else"
            for sub_step in step.get(taken, []) or []:
                try:
                    self._execute_step(sub_step, context)
                except Exception as e:
                    log.error(f"  branch.{taken} step failed: {e}")
            return f"branch.{taken}"

        # ── notify (Windows toast) ───────────────────────────────────────────
        if action == "notify":
            title   = self._substitute(step.get("title", "AXIOM"), context)
            message = self._substitute(step.get("message", ""), context)
            try:
                from plyer import notification
                notification.notify(
                    title=title, message=message,
                    app_name="AXIOM", timeout=10,
                )
                return f"notified: {message[:60]}"
            except Exception as e:
                log.warning(f"notify failed: {e}")
                return f"notify failed: {e}"

        # ── unknown action ───────────────────────────────────────────────────
        log.warning(f"Unknown action: {action}")
        return f"unknown action: {action}"

    # ─── Conditional helper ─────────────────────────────────────────────────

    @staticmethod
    def _evaluate(condition: str) -> bool:
        """
        Tiny condition evaluator. Supports:
          "{var} == value"   → equality
          "{var} != value"   → inequality
          "{var}"            → truthiness (non-empty, non-'false')
        Strings are stripped and lowercased for comparison.
        """
        condition = (condition or "").strip()
        if not condition:
            return False
        for op, fn in (("==", lambda a, b: a == b),
                       ("!=", lambda a, b: a != b)):
            if op in condition:
                left, right = condition.split(op, 1)
                left  = left.strip().strip("'\"").lower()
                right = right.strip().strip("'\"").lower()
                return fn(left, right)
        # Bare truthiness check
        v = condition.strip().strip("'\"").lower()
        return v not in ("", "false", "0", "no", "none")
