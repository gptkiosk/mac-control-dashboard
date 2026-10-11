"""Bounded, read-only GitHub CLI queries. Credentials stay in gh's credential store."""
from __future__ import annotations
import copy
import json
import re
import subprocess
import threading
import time

SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
REPO_FIELDS = "[.[] | {name: .full_name, description: .description, private: .private, archived: .archived, updated_at: .updated_at, branch: .default_branch}]"
ITEM_FIELDS = "[.[] | {number: .number, title: .title, user: .user.login, updated_at: .updated_at, draft: (.draft // false), is_pull: (.pull_request != null), labels: [.labels[].name]}]"

class GithubUnavailable(Exception):
    pass

class GithubReader:
    def __init__(self, binary: str):
        self.binary = binary
        self.cache = {}
        self.lock = threading.RLock()

    def query(self, endpoint: str, fields: str):
        try:
            result = subprocess.run([self.binary, "api", "--method", "GET", endpoint, "--jq", fields],
                                    capture_output=True, timeout=12, check=False)
            if result.returncode or len(result.stdout) > 4 * 1024 * 1024:
                raise GithubUnavailable()
            value = json.loads(result.stdout)
            if not isinstance(value, list):
                raise GithubUnavailable()
            return value
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise GithubUnavailable() from None

    def cached(self, key, loader):
        # Coalesce concurrent polls. Retry failed queries only after the same 60-second interval.
        with self.lock:
            old = self.cache.get(key)
            if old and time.monotonic() - old[0] < 60:
                return copy.deepcopy(old[1])
            try:
                value = {**loader(), "checked_at": time.time(), "error": None, "stale": False}
            except (GithubUnavailable, KeyError, TypeError):
                value = copy.deepcopy(old[1]) if old else {"checked_at": None}
                value.update(error="GitHub unavailable. Check the existing gh login, repository access or rate limit.", stale=True)
            self.cache[key] = (time.monotonic(), value)
            return copy.deepcopy(value)

    def repos(self):
        def load():
            raw = self.query("user/repos?per_page=100&sort=updated", REPO_FIELDS)
            repos = []
            for r in raw[:100]:
                if not isinstance(r, dict) or not isinstance(r.get("name"), str) or not SLUG.fullmatch(r["name"]):
                    raise GithubUnavailable()
                repos.append({**r, "url": "https://github.com/" + r["name"]})
            return {"repos": repos, "limited": len(raw) >= 100}
        result = self.cached("repos", load)
        result.setdefault("repos", [])
        result.setdefault("limited", False)
        return result

    def details(self, name: str):
        if not SLUG.fullmatch(name) or name not in {r["name"] for r in self.repos()["repos"]}:
            return None
        def items(kind, cap):
            raw = self.query(f"repos/{name}/{kind}?state=open&per_page={cap}&sort=updated&direction=desc", ITEM_FIELDS)
            if any(not isinstance(r, dict) for r in raw):
                raise GithubUnavailable()
            selected = [r for r in raw if kind == "pulls" or not r.get("is_pull")]
            output = []
            for r in selected[:50]:
                if not isinstance(r.get("number"), int) or r["number"] <= 0:
                    raise GithubUnavailable()
                output.append({**r, "url": f"https://github.com/{name}/{'pull' if kind == 'pulls' else 'issues'}/{r['number']}"})
            return {"items": output, "limited": len(raw) >= cap or len(selected) > 50}
        # Each stream retains its last good result when the other stream fails.
        return {"name": name, "pulls": self.cached((name, "pulls"), lambda: items("pulls", 50)),
                "issues": self.cached((name, "issues"), lambda: items("issues", 100))}
