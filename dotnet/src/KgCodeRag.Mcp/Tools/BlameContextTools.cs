using System.ComponentModel;
using ModelContextProtocol.Server;

namespace KgCodeRag.Mcp.Tools;

/// <summary>blame_context — combined ownership + coupling + work items for a file.</summary>
[McpServerToolType]
public sealed class BlameContextTools(
    GitHistoryTools gitTools,
    WorkItemTools workItemTools)
{
    [McpServerTool]
    [Description(
        "Return a combined context for a file: code ownership (authors), change coupling (co-changed files), " +
        "and work items linked to its commits. Aggregates code_ownership + change_coupling + work_items_for_code.")]
    public string BlameContext(
        [Description("Relative file path inside the repo.")] string filePath)
    {
        var sections = new List<string>();

        try { sections.Add(gitTools.CodeOwnership(filePath)); }
        catch (Exception ex) { sections.Add($"Ownership: error — {ex.Message}"); }

        try { sections.Add(gitTools.ChangeCoupling(filePath)); }
        catch (Exception ex) { sections.Add($"Coupling: error — {ex.Message}"); }

        try { sections.Add(workItemTools.WorkItemsForCode(filePath)); }
        catch (Exception ex) { sections.Add($"Work items: error — {ex.Message}"); }

        return ServerState.TruncateText(string.Join("\n\n---\n\n", sections));
    }
}
