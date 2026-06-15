namespace KgCodeRag.Config;

/// <summary>
/// A named subset of the mono-repo to index.
/// Mirrors the Python <c>ProjectScope</c> Pydantic model.
/// </summary>
public sealed class ProjectScope
{
    public string Description { get; init; } = "";

    /// <summary>Relative paths (from repo root) to index. Defaults to ["."] (whole repo).</summary>
    public List<string> Paths { get; init; } = ["."];

    /// <summary>
    /// Optional folder containing documentation *.md files, exposed as MCP resources.
    /// Can be absolute or relative to repo root.
    /// </summary>
    public string DocsDir { get; init; } = "";

    /// <summary>Explicit category → file-path overrides for MCP doc resources.</summary>
    public Dictionary<string, string> Docs { get; init; } = new();

    /// <summary>
    /// Returns a merged {category → absolute-path} dict for all documentation files.
    /// Auto-discovered files from DocsDir are extended by explicit Docs entries.
    /// </summary>
    public Dictionary<string, string> ResolveDocs(string repoRoot)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        // 1. Auto-discover *.md under docs_dir
        if (!string.IsNullOrWhiteSpace(DocsDir))
        {
            var baseDir = Path.IsPathRooted(DocsDir) ? DocsDir : Path.Combine(repoRoot, DocsDir);
            if (Directory.Exists(baseDir))
            {
                foreach (var mdFile in Directory.EnumerateFiles(baseDir, "*.md", SearchOption.AllDirectories))
                {
                    var rel = Path.GetRelativePath(baseDir, mdFile);
                    var category = Path.ChangeExtension(rel, null)
                        .Replace(Path.DirectorySeparatorChar, '-')
                        .Replace('/', '-');
                    result[category] = mdFile;
                }
            }
        }

        // 2. Explicit overrides
        foreach (var (category, rawPath) in Docs)
        {
            var p = Path.IsPathRooted(rawPath) ? rawPath : Path.Combine(repoRoot, rawPath);
            result[category] = p;
        }

        return result;
    }
}
