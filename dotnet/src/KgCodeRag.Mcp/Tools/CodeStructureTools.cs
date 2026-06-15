using System.ComponentModel;
using System.Text;
using KgCodeRag.Models;
using ModelContextProtocol.Server;

namespace KgCodeRag.Mcp.Tools;

[McpServerToolType]
public sealed class CodeStructureTools(ServerState state)
{
    private const int DefaultMatchLimit = 25;
    private const int DefaultRelationLimit = 50;
    private const int DefaultListLimit = 100;

    // ── lookup_symbol ─────────────────────────────────────────────────────

    [McpServerTool]
    [Description("Find code entities whose name contains the given string and return their immediate neighbourhood (relations).")]
    public string LookupSymbol(
        [Description("Partial or full symbol name to search for (case-insensitive).")] string name,
        [Description("Maximum number of matching entities to show.")] int maxMatches = DefaultMatchLimit,
        [Description("Maximum relations to show per match.")] int maxRelationsPerMatch = DefaultRelationLimit)
    {
        var kg = state.GetKg();
        var matches = kg.FindEntities(name: name);
        if (matches.Count == 0) return $"No entities found matching '{name}'.";

        var shown = matches.Take(maxMatches).ToList();
        var sb = new StringBuilder();
        sb.AppendLine(ServerState.SummarizeMatches(matches.Count, shown.Count, "matching entities"));
        sb.AppendLine();

        foreach (var ent in shown)
        {
            var loc = ent.FilePath.Length > 0 ? $" ({ent.FilePath}:{ent.LineStart})" : "";
            var sig = ent.Signature.Length > 0 ? $" — {ent.Signature}" : "";
            sb.AppendLine($"- [{ent.EntityType}] {ent.Name}{loc}{sig}");

            var relCount = 0;
            foreach (var rel in kg.Relations)
            {
                if (rel.Source == ent.QualifiedKey)
                    sb.AppendLine($"    --[{rel.RelationType}]--> {rel.Target}");
                else if (rel.Target == ent.QualifiedKey)
                    sb.AppendLine($"    <--[{rel.RelationType}]-- {rel.Source}");
                else continue;

                if (++relCount >= maxRelationsPerMatch)
                {
                    sb.AppendLine($"    ... capped at {maxRelationsPerMatch} relations ...");
                    break;
                }
            }
        }

        return ServerState.TruncateText(sb.ToString());
    }

    // ── file_overview ─────────────────────────────────────────────────────

    [McpServerTool]
    [Description("List all code entities defined in a specific file.")]
    public string FileOverview(
        [Description("Relative path of the file inside the repo (e.g. \"src/utils.py\").")] string filePath,
        [Description("Maximum number of entities to show.")] int maxEntities = DefaultListLimit)
    {
        var kg = state.GetKg();
        var resolved = state.ResolveFilePath(filePath);
        var searchPath = resolved ?? filePath;
        var matches = kg.FindEntities(filePath: searchPath);

        if (matches.Count == 0) return $"No entities found in '{filePath}'.";

        var shown = matches.Take(maxEntities).ToList();
        var sb = new StringBuilder();
        sb.AppendLine($"File: {searchPath} — {matches.Count} entities");
        sb.AppendLine(ServerState.SummarizeMatches(matches.Count, shown.Count, "entities"));
        sb.AppendLine();

        foreach (var ent in shown.OrderBy(e => e.LineStart))
        {
            var sig = ent.Signature.Length > 0 ? $" — {ent.Signature}" : "";
            sb.AppendLine($"- [{ent.EntityType}] {ent.Name} (L{ent.LineStart}){sig}");
        }

        return ServerState.TruncateText(sb.ToString());
    }

    // ── list_classes ──────────────────────────────────────────────────────

    [McpServerTool]
    [Description("List all classes in the codebase, optionally filtered by name.")]
    public string ListClasses(
        [Description("Optional name filter (case-insensitive substring match).")] string nameFilter = "",
        [Description("Maximum number of results.")] int limit = DefaultListLimit)
    {
        return ListByType(CodeEntityType.Class, nameFilter, limit, "classes");
    }

    // ── list_functions ────────────────────────────────────────────────────

    [McpServerTool]
    [Description("List all top-level functions in the codebase, optionally filtered by name.")]
    public string ListFunctions(
        [Description("Optional name filter (case-insensitive substring match).")] string nameFilter = "",
        [Description("Maximum number of results.")] int limit = DefaultListLimit)
    {
        return ListByType(CodeEntityType.Function, nameFilter, limit, "functions");
    }

    // ── call_graph ────────────────────────────────────────────────────────

    [McpServerTool]
    [Description("Show outgoing and incoming CALLS relations for a function or method.")]
    public string CallGraph(
        [Description("Function or method name (partial match supported).")] string functionName,
        [Description("Maximum matching functions.")] int maxMatches = DefaultMatchLimit,
        [Description("Maximum relations per match.")] int maxRelationsPerMatch = DefaultRelationLimit)
    {
        return ShowRelations(functionName, maxMatches, maxRelationsPerMatch,
            CodeRelationType.Calls, "call graph");
    }

    // ── inheritance_tree ──────────────────────────────────────────────────

    [McpServerTool]
    [Description("Show INHERITS and IMPLEMENTS relations for a class or interface.")]
    public string InheritanceTree(
        [Description("Class or interface name (partial match supported).")] string className,
        [Description("Maximum matching types.")] int maxMatches = DefaultMatchLimit,
        [Description("Maximum relations per match.")] int maxRelationsPerMatch = DefaultRelationLimit)
    {
        var kg = state.GetKg();
        var matches = kg.FindEntities(name: className,
                          entityType: null) // includes Class, Struct, Interface
                       .Where(e => e.EntityType is CodeEntityType.Class or
                                   CodeEntityType.Struct or CodeEntityType.Interface)
                       .Take(maxMatches)
                       .ToList();

        if (matches.Count == 0) return $"No type found matching '{className}'.";

        var sb = new StringBuilder();
        sb.AppendLine($"Inheritance tree for '{className}':");
        sb.AppendLine();

        foreach (var ent in matches)
        {
            sb.AppendLine($"[{ent.EntityType}] {ent.Name} ({ent.FilePath}:{ent.LineStart})");

            var relCount = 0;
            foreach (var rel in kg.Relations.Where(r =>
                (r.Source == ent.QualifiedKey || r.Target == ent.QualifiedKey) &&
                r.RelationType is CodeRelationType.Inherits or CodeRelationType.Implements))
            {
                var arrow = rel.Source == ent.QualifiedKey
                    ? $"  --[{rel.RelationType}]--> {rel.Target}"
                    : $"  <--[{rel.RelationType}]-- {rel.Source}";
                sb.AppendLine(arrow);
                if (++relCount >= maxRelationsPerMatch) break;
            }
            sb.AppendLine();
        }

        return ServerState.TruncateText(sb.ToString());
    }

    // ── Shared helpers ────────────────────────────────────────────────────

    private string ListByType(CodeEntityType type, string nameFilter, int limit, string noun)
    {
        var kg = state.GetKg();
        var matches = kg.FindEntities(
            name: string.IsNullOrWhiteSpace(nameFilter) ? null : nameFilter,
            entityType: type);

        if (matches.Count == 0)
            return $"No {noun} found" + (nameFilter.Length > 0 ? $" matching '{nameFilter}'" : "") + ".";

        var shown = matches.Take(limit).ToList();
        var sb = new StringBuilder();
        sb.AppendLine(ServerState.SummarizeMatches(matches.Count, shown.Count, noun));
        sb.AppendLine();
        foreach (var ent in shown.OrderBy(e => e.Name))
        {
            var loc = ent.FilePath.Length > 0 ? $" ({ent.FilePath}:{ent.LineStart})" : "";
            var doc = ent.Docstring.Length > 0 ? $" // {ent.Docstring[..Math.Min(60, ent.Docstring.Length)]}" : "";
            sb.AppendLine($"- {ent.Name}{loc}{doc}");
        }
        return ServerState.TruncateText(sb.ToString());
    }

    private string ShowRelations(
        string symbolName,
        int maxMatches,
        int maxRelationsPerMatch,
        CodeRelationType relType,
        string label)
    {
        var kg = state.GetKg();
        var matches = kg.FindEntities(name: symbolName).Take(maxMatches).ToList();
        if (matches.Count == 0) return $"No entities found matching '{symbolName}'.";

        var sb = new StringBuilder();
        sb.AppendLine($"{label} for '{symbolName}':");
        sb.AppendLine();

        foreach (var ent in matches)
        {
            sb.AppendLine($"[{ent.EntityType}] {ent.Name} ({ent.FilePath}:{ent.LineStart})");
            var relCount = 0;
            foreach (var rel in kg.Relations.Where(r =>
                r.RelationType == relType &&
                (r.Source == ent.QualifiedKey || r.Target == ent.QualifiedKey)))
            {
                var arrow = rel.Source == ent.QualifiedKey
                    ? $"  calls: {rel.Target}"
                    : $"  called by: {rel.Source}";
                sb.AppendLine(arrow);
                if (++relCount >= maxRelationsPerMatch) break;
            }
            sb.AppendLine();
        }

        return ServerState.TruncateText(sb.ToString());
    }
}
