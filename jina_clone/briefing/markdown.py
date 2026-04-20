from io import StringIO

from jina_clone.briefing.schema import Briefing


def briefing_to_markdown(b: Briefing) -> str:
    out = StringIO()
    out.write(f"# {b.date} — {b.title} · {b.volume}\n\n")
    out.write(f"## Lead: {b.lead.headline}\n")
    out.write(f"*{b.lead.deck}*\n\n")
    out.write(f"{b.lead.body}\n\n")
    out.write("**At a glance:**\n")
    for item in b.lead.at_a_glance:
        out.write(f"- {item}\n")
    out.write("\n")
    for panel in b.panels:
        out.write(f"## {panel.section}\n")
        out.write(f"**{panel.lede_headline}**\n\n")
        out.write(f"{panel.lede_body}\n\n")
        for item in panel.also:
            out.write(f"- **{item.headline}** — {item.body}\n")
        out.write("\n")
    out.write("## Briefs\n")
    for brief in b.briefs:
        out.write(f"- **{brief.topic}** — {brief.body}\n")
    out.write("\n")
    out.write(f"## Data point: {b.data_point.value}\n")
    out.write(f"{b.data_point.context}\n\n")
    out.write("## On this day\n")
    out.write(f"**{b.on_this_day.year_and_title}**\n\n")
    out.write(f"{b.on_this_day.body}\n\n")
    out.write(f"> {b.pull_quote}\n")
    return out.getvalue()
