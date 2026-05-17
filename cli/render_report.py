"""Render a TradingAgents complete_report.md into a single self-contained HTML.

Usage::

    python -m cli.render_report ~/.tradingagents/logs/NVDA/2026-05-17

Output: ``complete_report.html`` written next to the source markdown.

The HTML embeds its CSS so the file is portable (email it, drop in dropbox,
open offline). Left sidebar = section nav with anchor links; right = rendered
markdown with code, tables, lists, and bold sections preserved.
"""

from __future__ import annotations

import json
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from markdown_it import MarkdownIt

CSS = """
:root {
  --bg: #0e1116;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --muted: #8b949e;
  --link: #58a6ff;
  --accent: #d29922;
  --code-bg: #1c2128;
  --good: #3fb950;
  --bad: #f85149;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  font-size: 14px;
}
.layout { display: flex; min-height: 100vh; }
nav.sidebar {
  width: 280px;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  background: var(--surface);
  border-right: 1px solid var(--border);
  padding: 24px 16px;
  flex-shrink: 0;
}
nav.sidebar h2 { color: var(--accent); font-size: 16px; margin: 0 0 12px; }
nav.sidebar .meta { color: var(--muted); font-size: 12px; margin-bottom: 20px; }
nav.sidebar ul { list-style: none; margin: 0; padding: 0; }
nav.sidebar > ul > li { margin-bottom: 6px; }
nav.sidebar a {
  color: var(--text);
  text-decoration: none;
  display: block;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 13px;
}
nav.sidebar a:hover { background: rgba(88,166,255,0.1); color: var(--link); }
nav.sidebar .level-3 a { padding-left: 18px; color: var(--muted); font-size: 12px; }
main { flex: 1; padding: 32px 56px; max-width: 1100px; }
main h1 {
  border-bottom: 1px solid var(--border);
  padding-bottom: 12px;
  margin-top: 0;
  color: var(--accent);
}
main h2 {
  margin-top: 36px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
  color: var(--link);
}
main h3 { margin-top: 28px; color: var(--text); }
main h4 { margin-top: 20px; color: var(--muted); }
main p { margin: 12px 0; }
main blockquote {
  border-left: 3px solid var(--border);
  margin: 16px 0;
  padding: 4px 16px;
  color: var(--muted);
  background: rgba(255,255,255,0.02);
}
main code {
  background: var(--code-bg);
  padding: 2px 6px;
  border-radius: 3px;
  font-family: "Cascadia Code", Consolas, Menlo, monospace;
  font-size: 12.5px;
}
main pre {
  background: var(--code-bg);
  padding: 14px 16px;
  border-radius: 6px;
  overflow-x: auto;
  border: 1px solid var(--border);
}
main pre code { background: transparent; padding: 0; }
main table {
  border-collapse: collapse;
  margin: 16px 0;
  width: 100%;
}
main th, main td {
  border: 1px solid var(--border);
  padding: 8px 12px;
  text-align: left;
}
main th { background: var(--surface); }
main a { color: var(--link); }
main strong { color: var(--accent); font-weight: 600; }
main ul, main ol { padding-left: 24px; }
main li { margin: 4px 0; }
main hr { border: none; border-top: 1px solid var(--border); margin: 24px 0; }
.rating-badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  margin-left: 8px;
}
.rating-buy, .rating-overweight { background: rgba(63,185,80,0.2); color: var(--good); }
.rating-hold { background: rgba(210,153,34,0.2); color: var(--accent); }
.rating-underweight, .rating-sell { background: rgba(248,81,73,0.2); color: var(--bad); }
.exec-meta {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 16px 20px;
  margin: 16px 0 32px;
  font-size: 13px;
}
.exec-meta h2 { margin-top: 0; border: none; color: var(--accent); font-size: 15px; }
.exec-meta .summary-row { display: flex; flex-wrap: wrap; gap: 18px; color: var(--muted); margin-bottom: 10px; }
.exec-meta .summary-row span { color: var(--text); font-weight: 500; margin-left: 4px; }
.exec-meta table { width: 100%; margin: 8px 0 0; }
.exec-meta th, .exec-meta td { padding: 5px 10px; font-size: 12px; }
.exec-meta td.num { font-family: "Cascadia Code", Consolas, monospace; text-align: right; color: var(--muted); }
.exec-meta td.cost { color: var(--accent); font-weight: 600; }
.exec-meta td.model { color: var(--link); }
"""


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.strip()).lower()
    return re.sub(r"[-\s]+", "-", s)


def _build_nav(html: str) -> str:
    """Scan rendered HTML for h2/h3 tags and build a nav tree."""
    pattern = re.compile(r"<h([23])>(.+?)</h\1>", re.DOTALL)
    items = []
    for level, raw in pattern.findall(html):
        text = re.sub(r"<[^>]+>", "", raw).strip()
        if not text:
            continue
        anchor = _slugify(text)
        items.append((int(level), text, anchor))

    parts = ["<ul>"]
    for level, text, anchor in items:
        klass = "level-2" if level == 2 else "level-3"
        parts.append(f'<li class="{klass}"><a href="#{anchor}">{text}</a></li>')
    parts.append("</ul>")
    return "\n".join(parts)


def _inject_anchors(html: str) -> str:
    """Add id="..." to every h2/h3 so the nav anchors resolve."""

    def repl(m):
        level = m.group(1)
        body = m.group(2)
        text = re.sub(r"<[^>]+>", "", body).strip()
        anchor = _slugify(text)
        return f'<h{level} id="{anchor}">{body}</h{level}>'

    return re.sub(r"<h([23])>(.+?)</h\1>", repl, html, flags=re.DOTALL)


def _highlight_rating(html: str) -> str:
    """Wrap `**Rating**: X` style mentions in a coloured badge."""
    rating_words = ("buy", "overweight", "hold", "underweight", "sell")

    def repl(m):
        word = m.group(1)
        return f'<span class="rating-badge rating-{word.lower()}">{word}</span>'

    pattern = re.compile(
        r"<strong>Rating</strong>:\s*(" + "|".join(rating_words) + r")\b",
        re.IGNORECASE,
    )
    return pattern.sub(repl, html)


def _render_executor_meta(meta: dict) -> str:
    """Render the executor_meta.json contents into an HTML summary card."""
    if not meta:
        return ""

    # Aggregate per-model totals across nodes.
    model_totals: dict = {}
    for entry in meta.get("model_usage_per_node") or []:
        for model_name, stats in (entry.get("models") or {}).items():
            t = model_totals.setdefault(
                model_name,
                {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0},
            )
            t["input"] += stats.get("inputTokens", 0)
            t["output"] += stats.get("outputTokens", 0)
            t["cache_read"] += stats.get("cacheReadInputTokens", 0)
            t["cache_write"] += stats.get("cacheCreationInputTokens", 0)
            t["cost"] += stats.get("costUSD", 0.0)

    executor = meta.get("executor", "—")
    n_nodes = meta.get("n_nodes", 0)
    total_cost = meta.get("total_cost_usd")
    elapsed = meta.get("elapsed_seconds", 0)
    mins = elapsed // 60
    secs = elapsed % 60

    summary_row = (
        f'<div class="summary-row">'
        f"<div>Executor:<span>{executor}</span></div>"
        f"<div>Nodes:<span>{n_nodes}</span></div>"
        f"<div>Elapsed:<span>{mins}m {secs:02d}s</span></div>"
        + (f"<div>Total cost (equiv.):<span>${total_cost:.4f}</span></div>" if total_cost is not None else "")
        + "</div>"
    )

    if model_totals:
        rows = "".join(
            f"<tr>"
            f'<td class="model">{name}</td>'
            f'<td class="num">{t["input"]:,}</td>'
            f'<td class="num">{t["output"]:,}</td>'
            f'<td class="num">{t["cache_read"]:,}</td>'
            f'<td class="num">{t["cache_write"]:,}</td>'
            f'<td class="num cost">${t["cost"]:.4f}</td>'
            f"</tr>"
            for name, t in sorted(model_totals.items(), key=lambda x: -x[1]["cost"])
        )
        table = (
            "<table>"
            "<thead><tr>"
            "<th>Model</th><th>Input</th><th>Output</th>"
            "<th>Cache read</th><th>Cache write</th><th>Cost</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody>"
            "</table>"
        )
    else:
        table = "<p style='color:var(--muted)'>No per-model usage recorded (API mode or older run).</p>"

    return (
        '<div class="exec-meta">'
        '<h2>Run metadata</h2>'
        f"{summary_row}"
        f"{table}"
        "</div>"
    )


def render_report(report_dir: Path) -> Path:
    md_path = report_dir / "complete_report.md"
    if not md_path.exists():
        raise FileNotFoundError(
            f"complete_report.md not found at {md_path}. "
            f"Did the run complete? Per-section files would be in "
            f"{report_dir}/reports/ if so."
        )

    md_text = md_path.read_text(encoding="utf-8")
    md = MarkdownIt("commonmark", {"breaks": False, "html": True}).enable("table")
    body_html = md.render(md_text)
    body_html = _inject_anchors(body_html)
    body_html = _highlight_rating(body_html)

    nav_html = _build_nav(body_html)

    # Optional executor metadata card (only present for CLI-executor runs
    # since v0.3 — earlier runs won't have executor_meta.json).
    meta_path = report_dir / "executor_meta.json"
    exec_meta_html = ""
    if meta_path.exists():
        try:
            exec_meta_html = _render_executor_meta(json.loads(meta_path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            exec_meta_html = ""

    ticker = report_dir.parent.name
    analysis_date = report_dir.name
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{ticker} {analysis_date} — TradingAgents Report</title>
<style>{CSS}</style>
</head>
<body>
<div class="layout">
<nav class="sidebar">
<h2>{ticker} {analysis_date}</h2>
<div class="meta">Rendered {generated_at}</div>
{nav_html}
</nav>
<main>
{exec_meta_html}
{body_html}
</main>
</div>
</body>
</html>
"""

    out_path = report_dir / "complete_report.html"
    out_path.write_text(page, encoding="utf-8")
    return out_path


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m cli.render_report <results-dir> [--open]")
        print(
            "       <results-dir> is the run directory, e.g.\n"
            "       ~/.tradingagents/logs/NVDA/2026-05-17/"
        )
        return 1
    target = Path(sys.argv[1]).expanduser().resolve()
    open_after = "--open" in sys.argv[2:] or "-o" in sys.argv[2:]

    out = render_report(target)
    print(f"Wrote {out}")
    print(f"Open: file:///{str(out).replace(chr(92), '/')}")
    if open_after:
        webbrowser.open(out.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
