"""Quick call-graph test for a given symbol."""
from kg_rag.indexer import load_graph

kg = load_graph()

target_name = "ConvertSimulation"
matches = kg.find_entities(name=target_name)
print(f'Entities matching "{target_name}": {len(matches)}\n')

for fn in matches:
    print(f"=== {fn.name} ===")
    print(f"  Type: {fn.entity_type.value}")
    print(f"  File: {fn.file_path}:{fn.line_start}-{fn.line_end}")
    print(f"  Sig:  {fn.signature}")
    if fn.docstring:
        print(f"  Doc:  {fn.docstring[:120]}")

    calls_out = [r for r in kg.relations if r.source == fn.qualified_key and r.relation_type.value == "CALLS"]
    called_by = [r for r in kg.relations if r.target == fn.qualified_key and r.relation_type.value == "CALLS"]
    contains = [r for r in kg.relations if r.source == fn.qualified_key and r.relation_type.value == "CONTAINS"]
    defined_by = [r for r in kg.relations if r.target == fn.qualified_key and r.relation_type.value in ("DEFINES", "CONTAINS")]
    inherits = [r for r in kg.relations if r.source == fn.qualified_key and r.relation_type.value == "INHERITS"]

    if inherits:
        print(f"\n  Inherits from ({len(inherits)}):")
        for r in inherits:
            print(f"    ^ {r.target}")
    if defined_by:
        print(f"\n  Defined/contained by ({len(defined_by)}):")
        for r in defined_by:
            print(f"    @ {r.source}")
    if contains:
        print(f"\n  Contains ({len(contains)}):")
        for r in contains:
            print(f"    . {r.target}")
    if calls_out:
        print(f"\n  Calls ({len(calls_out)}):")
        for r in calls_out[:25]:
            print(f"    -> {r.target}")
        if len(calls_out) > 25:
            print(f"    ... and {len(calls_out) - 25} more")
    if called_by:
        print(f"\n  Called by ({len(called_by)}):")
        for r in called_by[:25]:
            print(f"    <- {r.source}")
        if len(called_by) > 25:
            print(f"    ... and {len(called_by) - 25} more")
    print()
