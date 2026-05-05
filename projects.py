"""
AXIOM Project Registry — workspace registry and voice resolution.

A "project" binds together a repo path, related URLs, default scenario,
Obsidian folder, and metadata. This replaces the flat `repos:` map with
a richer first-class concept.

Voice resolution priority (used by ProjectRegistry.resolve):
    1. Exact key match     ("axiom" → projects.axiom)
    2. Alias exact match   ("voice assistant" → projects.axiom via aliases)
    3. Name exact match    ("AXIOM" → projects.axiom)
    4. Fuzzy match         (rapidfuzz token_set_ratio >= 80)
    5. Substring fallback  (for when rapidfuzz isn't installed)

Backwards compat: any keys in `repos:` that don't appear under `projects:`
are auto-promoted to minimal project entries so existing config keeps working.

See AXIOM_development_plan.md §5 for the full specification.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("axiom.projects")


class ProjectRegistry:
    """
    Project registry with fuzzy voice resolution.

    Usage:
        registry = ProjectRegistry(config)
        project  = registry.resolve("axiom voice assistant")
        ctx      = registry.context_for(project)
    """

    def __init__(self, config: dict) -> None:
        self.config             = config
        self._projects          = self._load(config)
        self._active_key: Optional[str] = None  # session-active project

    # ─── Loading & normalization ────────────────────────────────────────────

    def _load(self, config: dict) -> dict[str, dict]:
        """Load + normalize projects, including legacy `repos:` fallback."""
        projects = {}

        # Primary: projects: section (rich format)
        for key, p in (config.get("projects", {}) or {}).items():
            projects[key.lower().strip()] = self._normalize(key, dict(p or {}))

        # Backwards compat: any repos: keys not already in projects:
        for key, path in (config.get("repos", {}) or {}).items():
            k = key.lower().strip()
            if k not in projects:
                projects[k] = self._normalize(key, {
                    "name":      key.title(),
                    "repo_path": path,
                    "_legacy":   True,
                })

        return projects

    @staticmethod
    def _normalize(key: str, p: dict) -> dict:
        """Fill in defaults so all downstream code can rely on the shape."""
        p.setdefault("name",             key.title())
        p.setdefault("aliases",          [])
        p.setdefault("repo_path",        "")
        p.setdefault("description",      "")
        p.setdefault("default_scenario", "coding_sequence")
        p.setdefault("websites",         [])
        p.setdefault("tags",             [])
        p.setdefault("obsidian_folder",  "")
        p["_key"] = key.lower().strip()
        return p

    # ─── Public API ─────────────────────────────────────────────────────────

    def list_projects(self) -> list[dict]:
        return list(self._projects.values())

    def get(self, key: str) -> Optional[dict]:
        if not key:
            return None
        return self._projects.get(key.lower().strip())

    def resolve(self, voice_input: str) -> Optional[dict]:
        """
        Match voice input to a project. Returns the project dict or None.

        Resolution order:
          1. Exact key match (case-insensitive)
          2. Underscore-normalized key match ("voice assistant" → voice_assistant)
          3. Alias exact match
          4. Name exact match
          5. Fuzzy match (rapidfuzz, threshold 80) on names + aliases
          6. Substring fallback if rapidfuzz unavailable
        """
        if not voice_input:
            return None

        query        = voice_input.lower().strip()
        normalized   = query.replace(" ", "_")

        # 1, 2 — exact key matches
        if query in self._projects:
            return self._projects[query]
        if normalized in self._projects:
            return self._projects[normalized]

        # 3 — exact alias match
        for project in self._projects.values():
            for alias in project.get("aliases", []) or []:
                if alias.lower().strip() == query:
                    return project

        # 4 — exact name match
        for project in self._projects.values():
            if project.get("name", "").lower().strip() == query:
                return project

        # 5 — fuzzy match
        candidate = self._fuzzy_match(query)
        if candidate:
            return candidate

        log.info(f"Could not resolve project from '{voice_input}'")
        return None

    def _fuzzy_match(self, query: str) -> Optional[dict]:
        try:
            from rapidfuzz import fuzz
        except ImportError:
            log.warning("rapidfuzz not installed — using substring fallback")
            for project in self._projects.values():
                if query in project["name"].lower():
                    return project
            return None

        best_score   = 0
        best_project = None
        for project in self._projects.values():
            candidates = [project["name"]] + list(project.get("aliases", []) or [])
            for c in candidates:
                score = fuzz.token_set_ratio(query, c.lower())
                if score > best_score:
                    best_score   = score
                    best_project = project

        if best_project and best_score >= 80:
            log.info(
                f"Fuzzy resolved '{query}' → {best_project['name']} "
                f"(score {best_score})"
            )
            return best_project
        return None

    # ─── Context for scenario substitution ──────────────────────────────────

    def context_for(self, project: dict) -> dict:
        """Build a substitution context dict from a project."""
        return {
            "project_name":        project.get("name", ""),
            "project_key":         project.get("_key", ""),
            "project_path":        project.get("repo_path", ""),
            "project_description": project.get("description", ""),
            "project_obsidian":    project.get("obsidian_folder", ""),
        }

    # ─── Active project (session state) ─────────────────────────────────────

    def set_active(self, voice_input: str) -> Optional[dict]:
        """Resolve and mark a project as active for this session."""
        project = self.resolve(voice_input)
        if project:
            self._active_key = project["_key"]
            log.info(f"Active project set: {project['name']}")
        return project

    def get_active(self) -> Optional[dict]:
        if self._active_key:
            return self._projects.get(self._active_key)
        return None

    # ─── Project status helpers ─────────────────────────────────────────────

    def status(self, project: dict) -> str:
        """
        Quick textual status summary for a project. Used by the
        `project_status` tool.
        """
        path = project.get("repo_path", "")
        if not path or not Path(path).exists():
            return f"{project['name']}: repo path missing or not found."

        lines = [f"{project['name']}"]
        if project.get("description"):
            lines.append(project["description"])

        # Branch + uncommitted changes via git
        try:
            branch = subprocess.run(
                "git rev-parse --abbrev-ref HEAD",
                shell=True, cwd=path,
                capture_output=True, text=True, timeout=4,
            ).stdout.strip() or "(no branch)"

            status = subprocess.run(
                "git status --porcelain",
                shell=True, cwd=path,
                capture_output=True, text=True, timeout=4,
            ).stdout.strip()

            modified = len([l for l in status.splitlines() if l]) if status else 0
            lines.append(f"branch: {branch}")
            lines.append(
                "no uncommitted changes" if modified == 0
                else f"{modified} uncommitted file(s)"
            )
        except Exception as e:
            lines.append(f"(git check failed: {e})")

        return " — ".join(lines)
