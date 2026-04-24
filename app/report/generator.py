from __future__ import annotations

import csv
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader

from app.config import Config
from app.storage.store import CategorizationRecord, FileStore, UserRecord

log = logging.getLogger(__name__)

CHART_COLORS = [
    "#6366f1", "#22c55e", "#ef4444", "#f59e0b",
    "#8b5cf6", "#14b8a6", "#f97316", "#64748b",
    "#ec4899", "#06b6d4", "#84cc16", "#e11d48",
]

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _apply_filters(records: List[CategorizationRecord], config: Config) -> List[CategorizationRecord]:
    f = config.filters
    result = records
    if f.include_categories:
        result = [r for r in result if r.category in f.include_categories]
    if f.exclude_categories:
        result = [r for r in result if r.category not in f.exclude_categories]
    if f.only_worth_checking:
        result = [r for r in result if r.worth_checking]
    if f.require_tags:
        lower_req = {t.lower() for t in f.require_tags}
        result = [r for r in result if any(t.lower() in lower_req for t in r.tags)]
    return result


class ReportService:
    def __init__(self, config: Config, store: FileStore) -> None:
        self.config = config
        self.store = store
        self._jinja = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=True,
        )

    def _build_report_context(
        self,
        records: List[CategorizationRecord],
        users_map: Dict[int, UserRecord],
    ) -> Dict[str, Any]:
        users_data = []
        for r in records:
            u = users_map.get(r.user_id)
            display_name = u.display_name if u else f"User#{r.user_id}"
            username = u.username if u else ""
            msgs = self.store.messages_for(r.user_id, limit=5)
            users_data.append({
                "user_id": r.user_id,
                "display_name": display_name,
                "username": username,
                "category": r.category,
                "worth_checking": r.worth_checking,
                "tags": r.tags,
                "summary": r.summary,
                "reasoning": r.reasoning,
                "message_count": r.message_count_seen,
                "messages": [m.text for m in msgs],
                "user_metadata": r.user_metadata,
            })

        category_counts = Counter(r.category for r in records)
        all_tags = sorted({t for r in records for t in r.tags})
        categories_list = sorted(category_counts.keys())

        return {
            "users_json": json.dumps(users_data, ensure_ascii=False),
            "total_users": len(records),
            "total_msgs": sum(r.message_count_seen for r in records),
            "total_wc": sum(1 for r in records if r.worth_checking),
            "categories_list": categories_list,
            "category_counts": dict(category_counts),
            "all_tags": all_tags,
            "chart_colors": json.dumps(CHART_COLORS),
            "model": self.config.model,
        }

    def render_report_html(self) -> str:
        records = _apply_filters(self.store.all_categorizations(), self.config)
        users_map = {u.user_id: u for u in self.store.all_users()}
        ctx = self._build_report_context(records, users_map)
        return self._jinja.get_template("report.html.j2").render(**ctx)

    def render_setup_html(self, settings: Dict[str, Any] | None = None) -> str:
        return self._jinja.get_template("setup.html.j2").render(settings=settings or {})

    def write_static_exports(self) -> None:
        """Write report.html, .csv, .json to data/exports/ for offline use."""
        exports_dir = Path(self.config.output_dir)
        exports_dir.mkdir(parents=True, exist_ok=True)

        records = _apply_filters(self.store.all_categorizations(), self.config)
        users_map = {u.user_id: u for u in self.store.all_users()}

        self._write_html(records, users_map, exports_dir)
        self._write_csv(records, users_map, exports_dir)
        self._write_json(records, users_map, exports_dir)

    def _write_html(self, records, users_map, exports_dir) -> None:
        ctx = self._build_report_context(records, users_map)
        html = self._jinja.get_template("report.html.j2").render(**ctx)
        path = exports_dir / "report.html"
        path.write_text(html, encoding="utf-8")
        log.info("HTML → %s", path)

    def _write_csv(self, records, users_map, exports_dir) -> None:
        path = exports_dir / "categorized_users.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "User ID", "Username", "First Name", "Last Name",
                "Display Name", "Category", "Worth Checking",
                "Tags", "Summary", "Reasoning",
                "Age", "City", "Country", "Profession",
                "Experience Years", "Languages", "Links", "Contact Info",
                "Message Count",
            ])
            for r in records:
                u = users_map.get(r.user_id)
                md = r.user_metadata or {}
                writer.writerow([
                    r.user_id,
                    u.username if u else "",
                    u.first_name if u else "",
                    u.last_name if u else "",
                    u.display_name if u else f"User#{r.user_id}",
                    r.category,
                    "Yes" if r.worth_checking else "No",
                    ", ".join(r.tags),
                    r.summary,
                    r.reasoning,
                    md.get("age") or "",
                    md.get("city") or "",
                    md.get("country") or "",
                    md.get("profession") or "",
                    md.get("experience_years") or "",
                    ", ".join(md.get("languages") or []),
                    ", ".join(md.get("links") or []),
                    md.get("contact_info") or "",
                    r.message_count_seen,
                ])
        log.info("CSV  → %s", path)

    def _write_json(self, records, users_map, exports_dir) -> None:
        path = exports_dir / "categorized_users.json"
        data = []
        for r in records:
            u = users_map.get(r.user_id)
            msgs = self.store.messages_for(r.user_id)
            data.append({
                "user_id": r.user_id,
                "username": u.username if u else "",
                "first_name": u.first_name if u else "",
                "last_name": u.last_name if u else "",
                "display_name": u.display_name if u else f"User#{r.user_id}",
                "category": r.category,
                "worth_checking": r.worth_checking,
                "tags": r.tags,
                "summary": r.summary,
                "reasoning": r.reasoning,
                "user_metadata": r.user_metadata,
                "message_count": r.message_count_seen,
                "messages": [m.text for m in msgs],
            })
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info("JSON → %s", path)
