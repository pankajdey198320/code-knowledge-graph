"""Debug ADO work item IDs."""
from dotenv import load_dotenv; load_dotenv()
from kg_rag.workitems import AdoClient

c = AdoClient()

# Use WIQL with $top to find actual work items
url = f"https://dev.azure.com/{c.org}/{c.project}/_apis/wit/wiql?api-version=7.0&$top=10"
query = {"query": "SELECT [System.Id] FROM WorkItems ORDER BY [System.Id] DESC"}
try:
    data = c._post(url, query)
    items = data.get("workItems", [])
    print(f"Found work items, showing first {len(items)}:")
    for wi in items:
        print(f"  ID: {wi['id']}")

    # Fetch details for those IDs
    if items:
        sample_ids = [wi["id"] for wi in items[:5]]
        print(f"\nFetching details for: {sample_ids}")
        details = c.get_work_items(sample_ids)
        for d in details:
            print(f"  #{d['id']}: [{d['work_item_type']}] {d['title']} ({d['state']})")
except Exception as e:
    print(f"WIQL error: {e}")

# Directly try the IDs from git commits
print("\n--- Direct ID tests ---")
for test_id in [1017, 1018, 111863]:
    try:
        result = c.get_work_items([test_id])
        if result:
            for d in result:
                print(f"  #{d['id']}: [{d['work_item_type']}] {d['title']}")
        else:
            print(f"  #{test_id}: not found (empty response)")
    except Exception as e:
        print(f"  #{test_id}: error - {e}")
