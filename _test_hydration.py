"""Test hydration from the mock cache."""
from kg_rag.indexer import load_graph
from kg_rag.workitems import hydrate_work_items
from pathlib import Path

g = load_graph(Path("data/cicd.pkl"))

# Before hydration
wis = [e for e in g.entities if e.entity_type.value == "work_item"]
print("BEFORE hydration:")
for w in wis:
    title = w.metadata.get("title", "(none)")
    print(f"  {w.name}  title={title}")

count = hydrate_work_items(g)
print(f"\nHydrated: {count}")

print("\nAFTER hydration:")
wis = [e for e in g.entities if e.entity_type.value == "work_item"]
for w in wis:
    title = w.metadata.get("title", "(none)")
    wtype = w.metadata.get("work_item_type", "?")
    state = w.metadata.get("state", "?")
    desc = w.metadata.get("description", "")[:60]
    print(f"  {w.name}")
    print(f"    [{wtype}] state={state}")
    print(f"    desc: {desc}")
