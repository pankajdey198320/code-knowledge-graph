using System.ComponentModel;
using System.Text;
using KgCodeRag.Models;
using ModelContextProtocol.Server;

namespace KgCodeRag.Mcp.Tools;

/// <summary>
/// Git-history tools: code_ownership, change_coupling, hot_spots.
/// Require the graph to have been indexed with git history (HasGitHistory == true).
/// The graph must contain MODIFIED_BY (file→author) and CO_CHANGED (file↔file) relations
/// built by the GitHistoryBuilder (Phase 4 implementation).
/// </summary>
[McpServerToolType]
public sealed class GitHistoryTools(ServerState state)
{
    [McpServerTool]
    [Description(
        "Show which authors have modified a file most often, ranked by commit count. " +
        "Requires git history to have been built during indexing.")]
    public string CodeOwnership(
        [Description("Relative file path inside the repo (e.g. \"src/MyService.cs\").")] string filePath)
    {
        var resolved = state.ResolveFilePath(filePath);
        if (resolved is null) return $"File not found in graph: '{filePath}'";

        var kg = state.GetKg();
        if (!HasGitHistory(kg)) return GitHistoryNotAvailable();

        // Find MODIFIED_BY relations originating from this file
        var authorRels = kg.Relations
            .Where(r => r.RelationType == CodeRelationType.ModifiedBy &&
                        r.Source.StartsWith(resolved + "::", StringComparison.OrdinalIgnoreCase))
            .ToList();

        if (authorRels.Count == 0)
            return $"No git history found for '{resolved}'. Ensure the graph was built with --git.";

        var sb = new StringBuilder();
        sb.AppendLine($"## Code Ownership: {resolved}");
        sb.AppendLine();

        var ranked = authorRels
            .Select(r => new
            {
                Author = r.Target,
                CommitCount = r.Metadata.TryGetValue("commit_count", out var c) ? int.Parse(c) : 1,
                Email = r.Metadata.GetValueOrDefault("email", ""),
            })
            .OrderByDescending(a => a.CommitCount)
            .ToList();

        foreach (var a in ranked)
            sb.AppendLine($"- {a.Author} ({a.Email}) — {a.CommitCount} commit(s)");

        return sb.ToString();
    }

    [McpServerTool]
    [Description(
        "Show files that are frequently co-changed (committed together) with the given file. " +
        "Useful for identifying hidden coupling and blast radius of changes.")]
    public string ChangeCoupling(
        [Description("Relative file path inside the repo.")] string filePath,
        [Description("Minimum co-change count to include (default 3).")] int minCount = 3)
    {
        var resolved = state.ResolveFilePath(filePath);
        if (resolved is null) return $"File not found in graph: '{filePath}'";

        var kg = state.GetKg();
        if (!HasGitHistory(kg)) return GitHistoryNotAvailable();

        // CO_CHANGED is stored on a file-level entity key (the FILE entity qualified key)
        var fileKey = kg.FindEntities(entityType: CodeEntityType.File, filePath: resolved)
                        .FirstOrDefault()?.QualifiedKey ?? resolved;

        var coupledFiles = kg.Relations
            .Where(r => r.RelationType == CodeRelationType.CoChanged &&
                        (r.Source == fileKey || r.Target == fileKey))
            .Select(r => new
            {
                OtherFile = r.Source == fileKey ? r.Target : r.Source,
                CoChangeCount = r.Metadata.TryGetValue("co_change_count", out var c) ? int.Parse(c) : 1,
            })
            .Where(x => x.CoChangeCount >= minCount)
            .OrderByDescending(x => x.CoChangeCount)
            .ToList();

        if (coupledFiles.Count == 0)
            return $"No co-changed files found for '{resolved}' (min_count={minCount}).";

        var sb = new StringBuilder();
        sb.AppendLine($"## Change Coupling: {resolved}");
        sb.AppendLine($"Files co-changed at least {minCount} time(s):");
        sb.AppendLine();
        foreach (var cf in coupledFiles)
            sb.AppendLine($"- {cf.OtherFile} — {cf.CoChangeCount} co-change(s)");

        return sb.ToString();
    }

    [McpServerTool]
    [Description(
        "Return the top N most frequently modified files — a proxy for code complexity hot-spots.")]
    public string HotSpots(
        [Description("Number of hot-spot files to return (default 20).")] int topN = 20)
    {
        var kg = state.GetKg();
        if (!HasGitHistory(kg)) return GitHistoryNotAvailable();

        // Count COMMITTED_IN relations per file
        var commitCounts = kg.Relations
            .Where(r => r.RelationType == CodeRelationType.CommittedIn)
            .GroupBy(r => r.Source)   // source = file entity key
            .Select(g => (FileKey: g.Key, CommitCount: g.Count()))
            .OrderByDescending(x => x.CommitCount)
            .Take(topN)
            .ToList();

        if (commitCounts.Count == 0)
            return "No git commit data found. Ensure the graph was built with --git.";

        var sb = new StringBuilder();
        sb.AppendLine($"## Hot Spots (top {topN} most-changed files)");
        sb.AppendLine();
        foreach (var (fileKey, count) in commitCounts)
        {
            // fileKey is the entity's QualifiedKey; extract the file path prefix
            var filePart = fileKey.Contains("::") ? fileKey[..fileKey.IndexOf("::")] : fileKey;
            sb.AppendLine($"- {filePart} — {count} commit(s)");
        }
        return sb.ToString();
    }

    // ── Helpers ───────────────────────────────────────────────────────────

    private static bool HasGitHistory(KnowledgeGraph kg) =>
        kg.Relations.Any(r => r.RelationType is CodeRelationType.ModifiedBy or
                              CodeRelationType.CommittedIn);

    private static string GitHistoryNotAvailable() =>
        "Git history is not available in the current graph. " +
        "Re-index the project with git history enabled (set enable_git=true or use --git flag).";
}
