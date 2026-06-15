using System.ComponentModel;
using System.Text;
using KgCodeRag.Models;
using ModelContextProtocol.Server;

namespace KgCodeRag.Mcp.Tools;

/// <summary>
/// Azure DevOps work item tools: work_items_for_code, code_for_work_item, work_item_details.
/// Require the graph to have been built with ADO integration (HasWorkItems == true).
/// Work item metadata is stored on LINKED_TO relations and WORK_ITEM entities.
/// </summary>
[McpServerToolType]
public sealed class WorkItemTools(ServerState state)
{
    [McpServerTool]
    [Description(
        "Return Azure DevOps work items linked to commits that touched the given file. " +
        "Requires work items to have been hydrated during indexing.")]
    public string WorkItemsForCode(
        [Description("Relative file path inside the repo.")] string filePath)
    {
        var resolved = state.ResolveFilePath(filePath);
        if (resolved is null) return $"File not found in graph: '{filePath}'";

        var kg = state.GetKg();
        if (!HasWorkItems(kg)) return WorkItemsNotAvailable();

        // Walk: file → COMMITTED_IN → commit → LINKED_TO → work_item
        var fileKey = resolved;
        var commitKeys = kg.Relations
            .Where(r => r.RelationType == CodeRelationType.CommittedIn &&
                        r.Source.StartsWith(fileKey + "::", StringComparison.OrdinalIgnoreCase))
            .Select(r => r.Target)
            .ToHashSet();

        var wiIds = kg.Relations
            .Where(r => r.RelationType == CodeRelationType.LinkedTo && commitKeys.Contains(r.Source))
            .Select(r => r.Target)
            .Distinct()
            .ToList();

        if (wiIds.Count == 0)
            return $"No work items found linked to '{resolved}'.";

        var sb = new StringBuilder();
        sb.AppendLine($"## Work Items for: {resolved}");
        sb.AppendLine();

        foreach (var wiId in wiIds)
        {
            var wiEnt = kg.GetEntity(wiId) ??
                        kg.FindEntities(name: wiId, entityType: CodeEntityType.WorkItem).FirstOrDefault();
            if (wiEnt is not null)
            {
                var title = wiEnt.Metadata.GetValueOrDefault("title", "(title not loaded)");
                var wiType = wiEnt.Metadata.GetValueOrDefault("type", "WorkItem");
                var state_ = wiEnt.Metadata.GetValueOrDefault("state", "");
                sb.AppendLine($"- [{wiType}] #{wiEnt.Name} — {title} ({state_})");
            }
            else
            {
                sb.AppendLine($"- #{wiId}");
            }
        }

        return sb.ToString();
    }

    [McpServerTool]
    [Description(
        "Return the files that were changed as part of a given Azure DevOps work item.")]
    public string CodeForWorkItem(
        [Description("Work item ID (numeric, e.g. \"12345\" or \"AB#12345\").")] string workItemId)
    {
        // Normalise: strip "AB#" prefix if present
        var id = workItemId.TrimStart().TrimStart('#');
        if (id.StartsWith("AB#", StringComparison.OrdinalIgnoreCase)) id = id[3..];

        var kg = state.GetKg();
        if (!HasWorkItems(kg)) return WorkItemsNotAvailable();

        // Find commits linked to this work item
        var commitKeys = kg.Relations
            .Where(r => r.RelationType == CodeRelationType.LinkedTo &&
                        r.Target.Contains(id, StringComparison.OrdinalIgnoreCase))
            .Select(r => r.Source)
            .ToHashSet();

        if (commitKeys.Count == 0)
            return $"No commits found linked to work item #{id}.";

        // Find files committed in those commits
        var files = kg.Relations
            .Where(r => r.RelationType == CodeRelationType.CommittedIn && commitKeys.Contains(r.Target))
            .Select(r =>
            {
                var src = r.Source;
                return src.Contains("::") ? src[..src.IndexOf("::")] : src;
            })
            .Distinct()
            .OrderBy(f => f)
            .ToList();

        var sb = new StringBuilder();
        sb.AppendLine($"## Files changed for work item #{id}");
        sb.AppendLine($"{files.Count} file(s) across {commitKeys.Count} commit(s):");
        sb.AppendLine();
        foreach (var f in files) sb.AppendLine($"- {f}");

        return sb.ToString();
    }

    [McpServerTool]
    [Description(
        "Return full details of an Azure DevOps work item: title, type, state, tags, and description. " +
        "Reads from the local work item cache if available.")]
    public string WorkItemDetails(
        [Description("Work item ID (numeric or with AB# prefix).")] string workItemId)
    {
        var id = workItemId.TrimStart().TrimStart('#');
        if (id.StartsWith("AB#", StringComparison.OrdinalIgnoreCase)) id = id[3..];

        var kg = state.GetKg();
        var wiEnt = kg.GetEntity($"work_item::{id}@0") ??
                    kg.FindEntities(name: id, entityType: CodeEntityType.WorkItem).FirstOrDefault();

        if (wiEnt is null)
            return $"Work item #{id} not found in graph. Ensure ADO hydration was enabled at index time.";

        var sb = new StringBuilder();
        sb.AppendLine($"## Work Item #{id}");
        foreach (var (k, v) in wiEnt.Metadata)
            sb.AppendLine($"**{k}**: {v}");
        if (!string.IsNullOrEmpty(wiEnt.Docstring))
        {
            sb.AppendLine();
            sb.AppendLine("### Description");
            sb.AppendLine(wiEnt.Docstring);
        }

        return ServerState.TruncateText(sb.ToString());
    }

    // ── Helpers ───────────────────────────────────────────────────────────

    private static bool HasWorkItems(KnowledgeGraph kg) =>
        kg.Relations.Any(r => r.RelationType == CodeRelationType.LinkedTo);

    private static string WorkItemsNotAvailable() =>
        "Work item data is not available in the current graph. " +
        "Re-index with ADO credentials (ADO_ORG, ADO_PROJECT, ADO_WI_READ env vars).";
}
