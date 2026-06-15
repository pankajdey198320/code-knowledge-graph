using System.ComponentModel;
using KgCodeRag.Models;
using ModelContextProtocol.Server;

namespace KgCodeRag.Mcp.Tools;

[McpServerToolType]
public sealed class CodeSearchTools(ServerState state)
{
    // ── search_keywords ───────────────────────────────────────────────────

    [McpServerTool]
    [Description(
        "Fast keyword-based search across entity names, signatures, docstrings, and file paths. " +
        "Use for quick searches when you know specific keywords or names. " +
        "For semantic/conceptual searches use search_code instead (requires Ollama).")]
    public string SearchKeywords(
        [Description("Keywords to search for (space-separated, case-insensitive).")] string query,
        [Description("Maximum number of results (default 50).")] int maxResults = 50)
    {
        var kg = state.GetKg();
        var keywords = query.ToLowerInvariant().Split(' ', StringSplitOptions.RemoveEmptyEntries);

        var matches = new List<(Entity Entity, int Score)>();
        foreach (var ent in kg.Entities)
        {
            var searchable = $"{ent.Name} {ent.Signature} {ent.Docstring} {ent.FilePath}"
                .ToLowerInvariant();
            var score = keywords.Sum(kw => CountOccurrences(searchable, kw));
            if (score > 0) matches.Add((ent, score));
        }

        if (matches.Count == 0) return $"No entities found matching keywords: {query}";

        matches.Sort((a, b) => b.Score.CompareTo(a.Score));
        var shown = matches.Take(maxResults).ToList();

        var lines = new List<string>
        {
            $"Found {matches.Count} entities matching keywords: {query}",
            $"Showing top {shown.Count} by relevance:\n",
        };
        foreach (var (ent, _) in shown)
        {
            var loc = ent.FilePath.Length > 0 ? $" ({ent.FilePath}:{ent.LineStart})" : "";
            var sig = ent.Signature.Length > 0 ? $" — {ent.Signature[..Math.Min(80, ent.Signature.Length)]}" : "";
            lines.Add($"[{ent.EntityType}] {ent.Name}{loc}{sig}");
        }

        return ServerState.TruncateText(string.Join("\n", lines));
    }

    // ── search_code (semantic) ────────────────────────────────────────────

    [McpServerTool]
    [Description(
        "Semantic search over the code knowledge graph using Ollama embeddings. " +
        "Finds entities whose names, signatures, or docstrings are most similar to a natural-language query. " +
        "NOTE: Requires Ollama to be running with an embedding model (default: nomic-embed-text). " +
        "First call may take a moment to compute embeddings. " +
        "For fast keyword search use search_keywords instead.")]
    public async Task<string> SearchCode(
        [Description("Natural-language description of what you're looking for.")] string query,
        [Description("Number of results to return (default 10).")] int topK = 10,
        [Description("Maximum characters in response.")] int maxChars = ServerState.DefaultTextLimit)
    {
        var retriever = await state.EnsureRetrieverAsync(preload: false);
        var ctx = await retriever.RetrieveAsync(query);
        return ServerState.TruncateText(ctx.SubgraphText, maxChars);
    }

    // ── Helpers ───────────────────────────────────────────────────────────

    private static int CountOccurrences(string text, string kw)
    {
        var count = 0;
        var idx = 0;
        while ((idx = text.IndexOf(kw, idx, StringComparison.Ordinal)) >= 0)
        {
            count++;
            idx += kw.Length;
        }
        return count;
    }
}
