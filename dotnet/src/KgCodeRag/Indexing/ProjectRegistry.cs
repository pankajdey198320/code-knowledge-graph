using System.Text.Json;
using KgCodeRag.Models;

namespace KgCodeRag.Indexing;

/// <summary>
/// Manages the project registry: a JSON file that maps cache paths → GraphMetadata snapshots.
/// Mirrors the Python <c>_update_registry</c> / <c>list_indexed_projects</c> functions.
/// </summary>
public sealed class ProjectRegistry
{
    private readonly string _registryPath;

    public ProjectRegistry(string dataDir)
    {
        Directory.CreateDirectory(dataDir);
        _registryPath = Path.Combine(dataDir, "project_registry.json");
    }

    /// <summary>
    /// Update (or insert) the registry entry for <paramref name="cachePath"/>.
    /// </summary>
    public void Upsert(string cachePath, GraphMetadata metadata)
    {
        var registry = Load();
        var key = Path.GetFullPath(cachePath);
        registry[key] = new RegistryEntry
        {
            ProjectName = metadata.ProjectName,
            RepoRoot = metadata.RepoRoot,
            ScopePaths = metadata.ScopePaths,
            IndexedAt = metadata.IndexedAt,
            EntityCount = metadata.EntityCount,
            RelationCount = metadata.RelationCount,
            HasGitHistory = metadata.HasGitHistory,
            HasWorkItems = metadata.HasWorkItems,
            GraphPath = key,
        };
        Save(registry);
    }

    /// <summary>
    /// Returns all registry entries whose graph files still exist on disk.
    /// </summary>
    public List<RegistryEntry> ListExisting()
    {
        return Load()
            .Where(kv => File.Exists(kv.Key))
            .Select(kv => kv.Value)
            .ToList();
    }

    // ── Private ───────────────────────────────────────────────────────────

    private Dictionary<string, RegistryEntry> Load()
    {
        if (!File.Exists(_registryPath)) return new();
        try
        {
            var json = File.ReadAllText(_registryPath);
            return JsonSerializer.Deserialize<Dictionary<string, RegistryEntry>>(json, _options)
                   ?? new();
        }
        catch
        {
            return new();
        }
    }

    private void Save(Dictionary<string, RegistryEntry> registry)
    {
        var json = JsonSerializer.Serialize(registry, _options);
        File.WriteAllText(_registryPath, json);
    }

    private static readonly JsonSerializerOptions _options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        WriteIndented = true,
    };
}

/// <summary>A single row in the project registry JSON.</summary>
public sealed class RegistryEntry
{
    public string ProjectName { get; set; } = "";
    public string RepoRoot { get; set; } = "";
    public List<string> ScopePaths { get; set; } = [];
    public string IndexedAt { get; set; } = "";
    public int EntityCount { get; set; }
    public int RelationCount { get; set; }
    public bool HasGitHistory { get; set; }
    public bool HasWorkItems { get; set; }
    public string GraphPath { get; set; } = "";
}
