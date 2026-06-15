using KgCodeRag.Config;
using KgCodeRag.Embeddings;
using KgCodeRag.Indexing;
using KgCodeRag.Models;
using KgCodeRag.Retrieval;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace KgCodeRag.Mcp;

/// <summary>
/// Singleton server state: holds the active knowledge graph, retriever, and
/// project configuration.  Thread-safe via <see cref="SemaphoreSlim"/>.
/// Mirrors the Python module-level globals in <c>mcp_server.py</c>.
/// </summary>
public sealed class ServerState : IAsyncDisposable
{
    private readonly ILogger<ServerState> _logger;
    private readonly SemaphoreSlim _lock = new(1, 1);

    // ── Mutable state (guarded by _lock) ──────────────────────────────────
    private KnowledgeGraph? _kg;
    private GraphMetadata? _metadata;
    private GraphRetriever? _retriever;
    private OllamaEmbedder? _embedder;
    private string _activeProject = "";
    private bool _embedderLoaded;
    /// <summary>True once the embedding model has been initialised for the active project.</summary>
    public bool IsEmbedderLoaded => _embedderLoaded;

    // ── Configuration (immutable after construction) ─────────────────────
    public ProjectsConfig ProjectsConfig { get; }
    public AppSettings Settings { get; }
    private readonly KgIndexer _indexer;
    private readonly ProjectRegistry _registry;

    public const int DefaultTextLimit = 12_000;

    public ServerState(ILogger<ServerState>? logger = null)
    {
        _logger = logger ?? NullLogger<ServerState>.Instance;
        Settings = AppSettings.Default;
        ProjectsConfig = ProjectsConfig.Load();
        _indexer = new KgIndexer();
        _activeProject = ProjectsConfig.DefaultProjectName(Settings.ActiveProject);
        _registry = new ProjectRegistry(Settings.DataDir);
    }

    // ── Public read accessors (no lock needed for read-only snapshots) ────

    public string ActiveProject
    {
        get { lock (_lock) return _activeProject; }
    }

    public KnowledgeGraph GetKg()
    {
        if (_kg is null) LoadGraph(_activeProject);
        return _kg!;
    }

    public GraphRetriever? GetRetriever() => _retriever;

    public ProjectRegistry Registry => _registry;

    // ── Graph management ──────────────────────────────────────────────────

    /// <summary>Load (or build) graph for <paramref name="project"/>; called at startup.</summary>
    public void LoadGraph(string? project = null)
    {
        _lock.Wait();
        try
        {
            var targetProject = ProjectsConfig.DefaultProjectName(project ?? _activeProject);
            if (_kg != null && targetProject == _activeProject) return;

            var cachePath = ProjectsConfig.GraphCachePath(targetProject);
            if (File.Exists(cachePath))
            {
                _logger.LogInformation("Loading '{Project}' graph from {Path}", targetProject, cachePath);
                var (kg, meta) = _indexer.LoadGraph(cachePath);
                _kg = kg;
                _metadata = meta;
            }
            else
            {
                _logger.LogInformation("No cache found — indexing project '{Project}'", targetProject);
                var repoRoot = ProjectsConfig.GetRepoRoot();
                List<string>? scopePaths = null;
                if (ProjectsConfig.Projects.ContainsKey(targetProject))
                    scopePaths = ProjectsConfig.ResolveAbsolutePaths(targetProject);

                _kg = _indexer.IndexRepo(repoRoot, scopePaths: scopePaths,
                    progress: new ConsoleProgress());

                _metadata = new GraphMetadata
                {
                    ProjectName = targetProject,
                    RepoRoot = repoRoot,
                    ScopePaths = scopePaths?.Select(p => Path.GetRelativePath(repoRoot, p)).ToList() ?? ["."],
                    IndexedAt = DateTime.UtcNow.ToString("O"),
                };
                _indexer.SaveGraph(_kg, _metadata, cachePath, _registry);
            }

            _activeProject = targetProject;
            _retriever = null;     // invalidate retriever for new project
            _embedderLoaded = false;
            _logger.LogInformation("Graph ready ({Project}): {E} entities, {R} relations",
                targetProject, _kg.Entities.Count, _kg.Relations.Count);
        }
        finally { _lock.Release(); }
    }

    /// <summary>Re-index from source code, overwriting the cache.</summary>
    public void ReindexRepo(string? repoRootOverride = null)
    {
        _lock.Wait();
        try
        {
            var repoRoot = repoRootOverride ?? ProjectsConfig.GetRepoRoot();
            List<string>? scopePaths = null;
            if (ProjectsConfig.Projects.ContainsKey(_activeProject))
                scopePaths = ProjectsConfig.ResolveAbsolutePaths(_activeProject);

            _logger.LogInformation("Re-indexing '{Project}'...", _activeProject);
            _kg = _indexer.IndexRepo(repoRoot, scopePaths: scopePaths,
                progress: new ConsoleProgress());

            _metadata = new GraphMetadata
            {
                ProjectName = _activeProject,
                RepoRoot = repoRoot,
                ScopePaths = scopePaths?.Select(p => Path.GetRelativePath(repoRoot, p)).ToList() ?? ["."],
                IndexedAt = DateTime.UtcNow.ToString("O"),
            };
            var cachePath = ProjectsConfig.GraphCachePath(_activeProject);
            _indexer.SaveGraph(_kg, _metadata, cachePath, _registry);

            // Invalidate embeddings cache
            _retriever = null;
            _embedderLoaded = false;
        }
        finally { _lock.Release(); }
    }

    /// <summary>Switch to a different project scope.</summary>
    public void SwitchProject(string projectName)
    {
        if (!ProjectsConfig.Projects.ContainsKey(projectName))
            throw new KeyNotFoundException($"Unknown project: '{projectName}'");
        _kg = null;
        _metadata = null;
        _retriever = null;
        _embedder?.Dispose();
        _embedder = null;
        _embedderLoaded = false;
        LoadGraph(projectName);
    }

    // ── Retriever (lazy, requires Ollama) ─────────────────────────────────

    /// <summary>
    /// Lazily initialise the embedder and retriever.
    /// Loads cached embeddings from disk if available; otherwise marks them
    /// as on-demand (first search will be slower).
    /// </summary>
    public async Task<GraphRetriever> EnsureRetrieverAsync(
        bool preload = false,
        CancellationToken ct = default)
    {
        await _lock.WaitAsync(ct);
        try
        {
            if (_retriever != null) return _retriever;

            var kg = _kg ?? throw new InvalidOperationException("Graph not loaded.");
            _embedder ??= new OllamaEmbedder();

            var cacheDir = Path.GetDirectoryName(ProjectsConfig.GraphCachePath(_activeProject))!;
            var embCachePath = Path.Combine(cacheDir, $"{_activeProject}_embeddings.json");

            var cacheLoaded = _embedder.LoadCache(embCachePath);

            if (preload || Settings.PreloadEmbeddings)
            {
                if (!cacheLoaded)
                {
                    var skipTypes = Settings.AggressiveEmbedding
                        ? OllamaEmbedder.AggressiveSkipTypes
                        : OllamaEmbedder.DefaultSkipTypes;

                    _logger.LogInformation("Pre-computing embeddings for project '{Project}'", _activeProject);
                    await _embedder.EmbedGraphAsync(kg, skipTypes, ct: ct);
                    _embedder.SaveCache(embCachePath);
                }
            }

            _retriever = new GraphRetriever(kg, _embedder, topK: 10, hops: 2);
            _embedderLoaded = true;
            return _retriever;
        }
        finally { _lock.Release(); }
    }

    // ── Metadata ──────────────────────────────────────────────────────────

    public GraphMetadata? Metadata => _metadata;

    // ── File path resolution ──────────────────────────────────────────────

    /// <summary>
    /// Resolve a user-supplied path to a canonical path in the graph.
    /// Tries exact match then suffix match.
    /// Throws <see cref="ArgumentException"/> for ambiguous suffix matches.
    /// </summary>
    public string? ResolveFilePath(string filePath)
    {
        var kg = GetKg();
        filePath = filePath.Replace('\\', '/');

        // Exact match
        if (kg.FindEntities(entityType: CodeEntityType.File, filePath: filePath)
              .Any(e => e.FilePath == filePath))
            return filePath;

        // Suffix match
        var suffix = "/" + filePath;
        var matches = kg.FindEntities(entityType: CodeEntityType.File)
            .Where(e => e.FilePath.EndsWith(suffix, StringComparison.OrdinalIgnoreCase))
            .Select(e => e.FilePath)
            .ToList();

        return matches.Count switch
        {
            0 => null,
            1 => matches[0],
            _ => throw new ArgumentException(
                $"Ambiguous path '{filePath}' matches:\n" +
                string.Join("\n", matches.Take(10).Select(m => $"  - {m}")) +
                (matches.Count > 10 ? $"\n  ... ({matches.Count} total)" : "") +
                "\nPlease provide a more specific path."),
        };
    }

    // ── Utilities ─────────────────────────────────────────────────────────

    public static string TruncateText(string text, int limit = DefaultTextLimit)
    {
        if (text.Length <= limit) return text;
        return $"{text[..limit]}\n\n... truncated {text.Length - limit} characters ...";
    }

    public static string SummarizeMatches(int total, int shown, string noun) =>
        total <= shown ? $"Found {total} {noun}." : $"Found {total} {noun}; showing first {shown}.";

    public async ValueTask DisposeAsync()
    {
        _embedder?.Dispose();
        _lock.Dispose();
        await ValueTask.CompletedTask;
    }

    // ── Inner types ───────────────────────────────────────────────────────

    private sealed class ConsoleProgress : IProgress<(int done, int total, string file)>
    {
        public void Report((int done, int total, string file) value) =>
            Console.Error.Write($"\r  [{value.done}/{value.total}] {Path.GetFileName(value.file)}   ");
    }
}
