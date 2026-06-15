namespace KgCodeRag.Models;

/// <summary>Metadata about an indexed knowledge graph (project name, timestamps, counts).</summary>
public sealed class GraphMetadata
{
    public string ProjectName { get; init; } = "";
    public string RepoRoot { get; init; } = "";
    /// <summary>Indexed scope paths relative to RepoRoot.</summary>
    public List<string> ScopePaths { get; init; } = [];
    /// <summary>ISO-8601 UTC timestamp when the graph was created.</summary>
    public string IndexedAt { get; set; } = "";
    public int EntityCount { get; set; }
    public int RelationCount { get; set; }
    public bool HasGitHistory { get; init; }
    public bool HasWorkItems { get; init; }
    /// <summary>Indexed file extensions, e.g. [".cs", ".py"].</summary>
    public List<string> Extensions { get; init; } = [];
    /// <summary>Git history window description if applicable.</summary>
    public string GitSince { get; init; } = "";
}
