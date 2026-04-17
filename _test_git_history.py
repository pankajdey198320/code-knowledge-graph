"""Quick test of the new git-history MCP tools."""
from kg_rag.indexer import load_graph
from pathlib import Path

g = load_graph(Path("data/cicd.pkl"))

target = ".teamcity/BladedNG/Calculation/WindowsTests/BuildTypes/CalculationResultsComparison_NG_to_4x.kt"

# Test ownership
mods = [r for r in g.relations if r.source == target and r.relation_type.value == "MODIFIED_BY"]
mods.sort(key=lambda r: int(r.metadata.get("commit_count", "0")), reverse=True)
print("=== OWNERSHIP ===")
for r in mods:
    email = r.metadata.get("email", "?")
    count = r.metadata.get("commit_count", "?")
    print(f"  {email:35s} {count} commits")

# Test co-change
print("\n=== CO-CHANGES (top 10) ===")
cochanged = []
for r in g.relations:
    if r.relation_type.value != "CO_CHANGED":
        continue
    cnt = int(r.metadata.get("co_change_count", "0"))
    if r.source == target:
        cochanged.append((r.target, cnt))
    elif r.target == target:
        cochanged.append((r.source, cnt))
cochanged.sort(key=lambda x: x[1], reverse=True)
for f, cnt in cochanged[:10]:
    print(f"  {cnt:3d}x  {f}")

# Test work items
print("\n=== WORK ITEMS ===")
commit_keys = [r.target for r in g.relations if r.source == target and r.relation_type.value == "COMMITTED_IN"]
wi_set = set()
for r in g.relations:
    if r.relation_type.value == "LINKED_TO" and r.source in commit_keys:
        wi_set.add(r.metadata.get("work_item_id", "?"))
print(f"  Linked work items: {wi_set or 'none'}")

# Authors
print("\n=== AUTHORS ===")
authors = [e for e in g.entities if e.entity_type.value == "author"]
for a in authors:
    print(f"  {a.name:30s} {a.metadata.get('email', '?')}")
