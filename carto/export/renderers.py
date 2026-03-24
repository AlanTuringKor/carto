"""
Report renderers for Carto.

Convert a ``CampaignReport`` into Markdown, JSON, or HTML.
Rendering is separated from assembly so the same report can
be exported in multiple formats.
"""

from __future__ import annotations

import json
from textwrap import indent

from carto.domain.report import CampaignReport, ReportSection


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


class MarkdownRenderer:
    """Renders a CampaignReport as readable Markdown."""

    def render(self, report: CampaignReport) -> str:
        lines: list[str] = []
        lines.append(f"# Campaign Report: {report.target_url}")
        lines.append("")
        lines.append(f"**Campaign ID:** `{report.campaign_id}`  ")
        lines.append(f"**Roles:** {', '.join(report.role_names)}  ")
        lines.append(f"**Generated:** {report.generated_at.isoformat()}")
        lines.append("")
        lines.append("---")
        lines.append("")

        for section in report.sections:
            lines.append(self._render_section(section, level=2))
            lines.append("")

        return "\n".join(lines)

    def _render_section(self, section: ReportSection, level: int) -> str:
        parts: list[str] = []
        heading = "#" * min(level, 6)
        parts.append(f"{heading} {section.title}")
        parts.append("")

        if section.content:
            parts.append(section.content)
            parts.append("")

        for sub in section.subsections:
            parts.append(self._render_section(sub, level + 1))
            parts.append("")

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


class JsonRenderer:
    """Renders a CampaignReport as structured JSON."""

    def render(self, report: CampaignReport) -> str:
        data = report.model_dump(mode="json")
        return json.dumps(data, indent=2, default=str)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


class HtmlRenderer:
    """
    Renders a CampaignReport as a standalone HTML document.

    Uses a simple, clean style suitable for browser viewing.
    Wraps the Markdown content in HTML structure.
    """

    def render(self, report: CampaignReport) -> str:
        md = MarkdownRenderer().render(report)
        # Simple HTML wrapping with basic styling
        return self._wrap_html(report.target_url, md)

    def _wrap_html(self, title: str, md_content: str) -> str:
        # Convert basic markdown to HTML-safe content
        html_body = self._md_to_html(md_content)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Carto Report: {title}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         max-width: 960px; margin: 2rem auto; padding: 0 1rem;
         color: #1a1a2e; background: #fafafa; line-height: 1.6; }}
  h1 {{ color: #16213e; border-bottom: 2px solid #0f3460; padding-bottom: 0.5rem; }}
  h2 {{ color: #0f3460; margin-top: 2rem; }}
  h3 {{ color: #533483; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; }}
  th {{ background: #e2e2e2; }}
  code {{ background: #e8e8e8; padding: 0.15rem 0.3rem; border-radius: 3px;
          font-size: 0.9em; }}
  hr {{ border: none; border-top: 1px solid #ccc; margin: 2rem 0; }}
  .warning {{ color: #b33; font-weight: bold; }}
  pre {{ background: #2d2d2d; color: #f8f8f2; padding: 1rem;
         border-radius: 6px; overflow-x: auto; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    @staticmethod
    def _md_to_html(md: str) -> str:
        """Minimal markdown-to-HTML conversion for report rendering."""
        import re

        lines = md.split("\n")
        html_lines: list[str] = []
        in_table = False
        in_list = False

        for line in lines:
            stripped = line.strip()

            # Headings
            if stripped.startswith("######"):
                html_lines.append(f"<h6>{stripped[7:].strip()}</h6>")
            elif stripped.startswith("#####"):
                html_lines.append(f"<h5>{stripped[6:].strip()}</h5>")
            elif stripped.startswith("####"):
                html_lines.append(f"<h4>{stripped[5:].strip()}</h4>")
            elif stripped.startswith("###"):
                html_lines.append(f"<h3>{stripped[4:].strip()}</h3>")
            elif stripped.startswith("##"):
                html_lines.append(f"<h2>{stripped[3:].strip()}</h2>")
            elif stripped.startswith("# "):
                html_lines.append(f"<h1>{stripped[2:].strip()}</h1>")

            # Horizontal rule
            elif stripped == "---":
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append("<hr>")

            # Table
            elif stripped.startswith("|"):
                cells = [c.strip() for c in stripped.split("|")[1:-1]]
                if all(c.replace("-", "") == "" for c in cells):
                    continue  # separator row
                if not in_table:
                    html_lines.append("<table>")
                    in_table = True
                    html_lines.append("<tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr>")
                else:
                    html_lines.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")

            # List item
            elif stripped.startswith("- "):
                if in_table:
                    html_lines.append("</table>")
                    in_table = False
                if not in_list:
                    html_lines.append("<ul>")
                    in_list = True
                content = stripped[2:]
                content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
                content = re.sub(r'`(.+?)`', r'<code>\1</code>', content)
                html_lines.append(f"<li>{content}</li>")

            # Empty line
            elif stripped == "":
                if in_table:
                    html_lines.append("</table>")
                    in_table = False
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False

            # Paragraph
            else:
                if in_table:
                    html_lines.append("</table>")
                    in_table = False
                content = stripped
                content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
                content = re.sub(r'`(.+?)`', r'<code>\1</code>', content)
                content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', content)
                html_lines.append(f"<p>{content}</p>")

        if in_table:
            html_lines.append("</table>")
        if in_list:
            html_lines.append("</ul>")

        return "\n".join(html_lines)
