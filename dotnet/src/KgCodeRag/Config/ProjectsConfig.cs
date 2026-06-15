using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace KgCodeRag.Config;

/// <summary>
/// Top-level configuration holding all defined project scopes.
/// Mirrors the Python <c>ProjectsConfig</c> Pydantic model.
///
/// Load precedence (first match wins):
///   1. KG_PROJECTS_JSON env var (raw JSON string)
///   2. KG_PROJECTS_FILE env var (path to a JSON file)
///   3. KG_REPO_ROOT + KG_SCOPE_PATHS + KG_PROJECT_NAME env vars (single-project shortcut)
///   4. projects.json file next to the executable
/// </summary>
public sealed class ProjectsConfig
{
    public string RepoRoot { get; init; } = "";
    public string CacheDir { get; init; } = "";
    public Dictionary<string, ProjectScope> Projects { get; init; } = new();

    // ── Load ─────────────────────────────────────────────────────────────

    public static ProjectsConfig Load(string? configFilePath = null)
    {
        // 1. Raw JSON env var
        var envJson = Env("KG_PROJECTS_JSON");
        if (!string.IsNullOrEmpty(envJson))
            return Deserialize(envJson);

        // 2. JSON file path env var
        var envFile = Env("KG_PROJECTS_FILE");
        if (!string.IsNullOrEmpty(envFile) && File.Exists(envFile))
            return Deserialize(File.ReadAllText(envFile));

        // 3. Individual env vars (single-project shortcut)
        var repoRoot = Env("KG_REPO_ROOT");
        var scopePathsRaw = Env("KG_SCOPE_PATHS") ?? "";
        if (!string.IsNullOrEmpty(repoRoot) || !string.IsNullOrEmpty(scopePathsRaw))
        {
            var projectName =
                Env("KG_PROJECT_NAME") ??
                Env("ACTIVE_PROJECT") ??
                "default";
            var cacheDir = Env("KG_CACHE_DIR") ?? "";
            var scopePaths = ParseScopePaths(scopePathsRaw);
            return new ProjectsConfig
            {
                RepoRoot = repoRoot ?? AppSettings.Default.RepoRoot,
                CacheDir = cacheDir,
                Projects = new()
                {
                    [projectName] = new ProjectScope
                    {
                        Description = Env("KG_PROJECT_DESCRIPTION") ??
                                      "Configured from environment",
                        Paths = scopePaths.Count > 0 ? scopePaths : ["."],
                    },
                },
            };
        }

        // 4. projects.json file
        var filePath = configFilePath ??
                       Path.Combine(AppContext.BaseDirectory, "projects.json");
        if (File.Exists(filePath))
            return Deserialize(File.ReadAllText(filePath));

        return new ProjectsConfig();
    }

    // ── Helpers ──────────────────────────────────────────────────────────

    public string GetRepoRoot() =>
        string.IsNullOrWhiteSpace(RepoRoot) ? AppSettings.Default.RepoRoot : RepoRoot;

    public string DefaultProjectName(string? preferred = null)
    {
        if (preferred != null && Projects.ContainsKey(preferred)) return preferred;
        var active = AppSettings.Default.ActiveProject;
        if (Projects.ContainsKey(active)) return active;
        if (Projects.ContainsKey("_full_")) return "_full_";
        return Projects.Keys.FirstOrDefault() ?? preferred ?? "_full_";
    }

    public List<string> ResolveAbsolutePaths(string projectName)
    {
        if (!Projects.TryGetValue(projectName, out var scope))
            throw new KeyNotFoundException($"Unknown project: '{projectName}'");
        var root = GetRepoRoot();
        return scope.Paths.Select(p => Path.Combine(root, p)).ToList();
    }

    /// <summary>
    /// Returns the JSON cache file path for a project.
    /// Uses a SHA-1 hash of the repo root to isolate caches across machines.
    /// </summary>
    public string GraphCachePath(string projectName)
    {
        var cacheRoot = !string.IsNullOrWhiteSpace(CacheDir)
            ? CacheDir
            : AppSettings.Default.DataDir;
        Directory.CreateDirectory(cacheRoot);
        var repoHash = Sha1Short(GetRepoRoot());
        var safeName = SanitizeName(projectName);
        return Path.Combine(cacheRoot, $"{safeName}-{repoHash}.json");
    }

    public List<string> ListProjectNames() => [.. Projects.Keys];

    // ── Private ───────────────────────────────────────────────────────────

    private static string? Env(string name) =>
        Environment.GetEnvironmentVariable(name) is { Length: > 0 } v ? v : null;

    private static ProjectsConfig Deserialize(string json) =>
        JsonSerializer.Deserialize<ProjectsConfig>(json, JsonOptions) ?? new();

    private static string Sha1Short(string input)
    {
        var bytes = SHA1.HashData(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes)[..10].ToLowerInvariant();
    }

    private static string SanitizeName(string name) =>
        new string(name.Select(c => char.IsLetterOrDigit(c) || c is '-' or '_' ? c : '_').ToArray())
            .Trim('_')
            .ToLowerInvariant();

    private static List<string> ParseScopePaths(string raw) =>
        raw.Split([',', ';'], StringSplitOptions.RemoveEmptyEntries)
           .Select(s => s.Trim())
           .Where(s => s.Length > 0)
           .ToList();

    internal static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = true,
    };
}
