"""Generate docs/ER_DIAGRAM.md (Mermaid) straight from the SQLAlchemy metadata so it never drifts."""
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app.models  # noqa
from app.db.session import Base

lines = ["```mermaid", "erDiagram"]
for t in Base.metadata.sorted_tables:
    lines.append(f"  {t.name} {{")
    for c in t.columns:
        kind = "PK" if c.primary_key else ("FK" if c.foreign_keys else ("UK" if c.unique else ""))
        typ = str(c.type).split("(")[0].replace(" ", "_")
        lines.append(f"    {typ} {c.name} {kind}".rstrip())
    lines.append("  }")
for t in Base.metadata.sorted_tables:
    for c in t.columns:
        for fk in c.foreign_keys:
            card = "o|" if c.nullable else "||"
            lines.append(f'  {fk.column.table.name} {card}--o{{ {t.name} : "{c.name}"')
lines.append("```")
out = pathlib.Path(__file__).resolve().parents[2] / "docs" / "ER_DIAGRAM.md"
out.parent.mkdir(exist_ok=True)
out.write_text("# ER Diagram (auto-generated)\n\nRegenerate with `python scripts/gen_er_diagram.py` from `backend/`.\n\n" + "\n".join(lines) + "\n")
print("wrote", out)
