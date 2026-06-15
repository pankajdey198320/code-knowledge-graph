using System.Text.Json;
using System.Text.Json.Serialization;
using KgCodeRag.Config;
using KgCodeRag.Models;
using KgCodeRag.Parsers;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace KgCodeRag.Indexing;

/// <summary>
/// Crawls a repo, parses source files, builds the knowledge graph, and manages
/// JSON cache files.  Mirrors the Python <c>indexer.py</c> module.
/// </summary>
public sealed class KgIndexer
{
    private readonly ParserRouter _router;
    private readonly ILogger<KgIndexer> _logger;

    public KgIndexer(ILogger<KgIndexer>? logger = null)
    {
        _router = new ParserRouter();
        _logger = logger ?? NullLogger<KgIndexer>.Instance;
    }

    // ── File discovery ────────────────────────────────────────────────────

    /// <summary>
    /// Walk <paramref name="repoRoot"/> (or scoped sub-paths) and return all
    /// parseable source files.  Ignores inaccessible directories and follows
    /// the same skip-dir list as the Python version.
    /// </summary>
    public List<string> DiscoverFiles(
        string repoRoot,
        IEnumerable<string>? extensions = null,
        IEnumerable<string>? scopePaths = null,
        IEnumerable<string>? skipDirs = null)
    {
        var exts = new HashSet<string>(
            (extensions ?? AppSettings.DefaultIndexExtensions),
            StringComparer.OrdinalIgnoreCase);

        var skip = new HashSet<string>(
            skipDirs ?? AppSettings.DefaultSkipDirs,
            StringComparer.OrdinalIgnoreCase);

        var roots = scopePaths?.Select(p => Path.GetFullPath(p)).ToList()
                    ?? [Path.GetFullPath(repoRoot)];

        var opts = new EnumerationOptions
        {
            RecurseSubdirectories = true,
            IgnoreInaccessible = true,
            AttributesToSkip = FileAttributes.ReparsePoint,
            MatchCasing = MatchCasing.CaseInsensitive,
        };

        var matched = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var root in roots)
        {
            if (!Directory.Exists(root))
            {
                _logger.LogWarning("Scope path does not exist, skipping: {Path}", root);
                continue;
            }

            foreach (var file in Directory.EnumerateFiles(root, "*", opts))
            {
                // Skip excluded directory segments
                var segments = Path.GetRelativePath(root, file).Split([Path.DirectorySeparatorChar, '/']);
                if (segments.Any(s => skip.Contains(s))) continue;

                var ext = Path.GetExtension(file);
                if (exts.Contains(ext) && ParserRouter.LanguageForExtension(ext) is not null)
                    matched.Add(file);
            }
        }

        return matched.OrderBy(f => f, StringComparer.OrdinalIgnoreCase).ToList();
    }

    // ── Indexing ──────────────────────────────────────────────────────────

    /// <summary>
    /// Parse every discovered source file and merge into one KnowledgeGraph.
    /// One bad file never aborts the whole run.
    /// </summary>
    public KnowledgeGraph IndexRepo(
        string repoRoot,
        IEnumerable<string>? extensions = null,
        IEnumerable<string>? scopePaths = null,
        IProgress<(int done, int total, string file)>? progress = null)
    {
        var files = DiscoverFiles(repoRoot, extensions, scopePaths);
        var kg = new KnowledgeGraph();
        var total = files.Count;

        for (var i = 0; i < total; i++)
        {
            var file = files[i];
            progress?.Report((i + 1, total, file));

            var parser = _router.GetParser(Path.GetExtension(file));
            if (parser is null) continue;

            try
            {
                var subKg = parser.ParseFile(file, repoRoot);
                kg.MergeFrom(subKg);
            }
            catch (Exception ex)
            {
                _logger.LogWarning("Skipping {File}: {Error}", file, ex.Message);
            }
        }

        return kg;
    }

    // ── Persistence ───────────────────────────────────────────────────────

    /// <summary>Serialise the graph + metadata to a JSON file and update the project registry.</summary>
    public void SaveGraph(
        KnowledgeGraph kg,
        GraphMetadata metadata,
        string cachePath,
        ProjectRegistry? registry = null)
    {
        // Stamp counts
        metadata.EntityCount = kg.Entities.Count;
        metadata.RelationCount = kg.Relations.Count;
        if (string.IsNullOrEmpty(metadata.IndexedAt))
            metadata.IndexedAt = DateTime.UtcNow.ToString("O");

        var persisted = PersistedGraph.From(kg, metadata);
        var dir = Path.GetDirectoryName(cachePath);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);

        var json = JsonSerializer.Serialize(persisted, _jsonOptions);
        File.WriteAllText(cachePath, json);

        registry?.Upsert(cachePath, metadata);
        _logger.LogInformation("Graph saved to {Path} ({E} entities, {R} relations)",
            cachePath, metadata.EntityCount, metadata.RelationCount);
    }

    /// <summary>Load graph + metadata from a JSON cache file.</summary>
    public (KnowledgeGraph Graph, GraphMetadata Metadata) LoadGraph(string cachePath)
    {
        var json = File.ReadAllText(cachePath);
        var persisted = JsonSerializer.Deserialize<PersistedGraph>(json, _jsonOptions)
                        ?? throw new InvalidDataException($"Cannot deserialise graph from {cachePath}");
        return persisted.Restore();
    }

    // ── Private ───────────────────────────────────────────────────────────

    private static readonly JsonSerializerOptions _jsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        WriteIndented = true,
        Converters =
        {
            new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower),
        },
    };
}
