using System.ComponentModel;
using System.Text;
using KgCodeRag.Models;
using ModelContextProtocol.Server;

namespace KgCodeRag.Mcp.Tools;

[McpServerToolType]
public sealed class GraphStatsTools(ServerState state)
{
    [McpServerTool]
    [Description("Return entity and relation counts, indexing timestamp, and feature status (git history, work items).")]
    public string GraphStats()
    {
        var kg = state.GetKg();
        var meta = state.Metadata;

        var sb = new StringBuilder();
        sb.AppendLine("## Knowledge Graph Statistics");
        sb.AppendLine();
        sb.AppendLine($"**Project**: {state.ActiveProject}");
        if (meta is not null)
        {
            sb.AppendLine($"**Repo root**: {meta.RepoRoot}");
            sb.AppendLine($"**Indexed**: {meta.IndexedAt}");
            sb.AppendLine($"**Scope paths**: {string.Join(", ", meta.ScopePaths)}");
            sb.AppendLine($"**Git history**: {(meta.HasGitHistory ? "yes" : "no")}");
            sb.AppendLine($"**Work items**: {(meta.HasWorkItems ? "yes" : "no")}");
        }
        sb.AppendLine();
        sb.AppendLine($"**Total entities**: {kg.Entities.Count:N0}");
        sb.AppendLine($"**Total relations**: {kg.Relations.Count:N0}");
        sb.AppendLine();

        // Breakdown by entity type
        sb.AppendLine("### Entity breakdown");
        foreach (var grp in kg.Entities
                     .GroupBy(e => e.EntityType)
                     .OrderByDescending(g => g.Count()))
            sb.AppendLine($"  {grp.Key,-14} {grp.Count(),6:N0}");

        sb.AppendLine();
        sb.AppendLine("### Relation breakdown");
        foreach (var grp in kg.Relations
                     .GroupBy(r => r.RelationType)
                     .OrderByDescending(g => g.Count()))
            sb.AppendLine($"  {grp.Key,-14} {grp.Count(),6:N0}");

        return sb.ToString();
    }

    [McpServerTool]
    [Description(
        "Re-index the active project from source code, rebuilding the graph cache. " +
        "WARNING: This may take several minutes for large repositories.")]
    public string ReindexRepo(
        [Description("Override repo root path. Leave empty to use the configured project root.")] string repoPath = "")
    {
        var repoOverride = string.IsNullOrWhiteSpace(repoPath) ? null : repoPath;
        state.ReindexRepo(repoOverride);
        var kg = state.GetKg();
        return $"Re-index complete. Graph now has {kg.Entities.Count:N0} entities and {kg.Relations.Count:N0} relations.";
    }
}
