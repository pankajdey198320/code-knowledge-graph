namespace KgCodeRag.Config;

/// <summary>
/// Application-wide settings resolved from environment variables.
/// Mirrors the Python <c>kg_rag/config.py</c> Settings class.
/// Env-var precedence: KG_CACHE_DIR → DATA_DIR → {BaseDirectory}/data
/// </summary>
public sealed class AppSettings
{
    // ── Ollama ──────────────────────────────────────────────────────────
    public string OllamaBaseUrl { get; } =
        Env("OLLAMA_BASE_URL") ?? "http://localhost:11434";

    public string LlmModel { get; } = Env("LLM_MODEL") ?? "llama3";

    /// <summary>Embedding model served by Ollama (default: nomic-embed-text).</summary>
    public string EmbeddingModel { get; } =
        Env("EMBEDDING_MODEL") ?? "nomic-embed-text";

    // ── Repo indexing ────────────────────────────────────────────────────
    public string RepoRoot { get; } =
        Env("KG_REPO_ROOT") ?? Env("REPO_ROOT") ?? ".";

    public string ActiveProject { get; } =
        Env("KG_PROJECT_NAME") ?? Env("ACTIVE_PROJECT") ?? "_full_";

    public static readonly string[] DefaultIndexExtensions =
        ".py,.cpp,.h,.hpp,.cs,.f90,.f95,.f03,.f08,.for,.fpp,.f,.kt,.kts,.ps1,.psm1,.psd1,.ts,.tsx,.js,.jsx"
        .Split(',');

    public static readonly HashSet<string> DefaultSkipDirs =
        new(StringComparer.OrdinalIgnoreCase)
        {
            ".git", "node_modules", "__pycache__", ".venv",
            "bin", "obj", "Debug", "Release", "build", "dist",
        };

    // ── Azure DevOps ─────────────────────────────────────────────────────
    public string AdoOrg { get; } = Env("ADO_ORG") ?? "";
    public string AdoProject { get; } = Env("ADO_PROJECT") ?? "";
    /// <summary>Personal access token with Work Items (read) scope.</summary>
    public string AdoPat { get; } = Env("ADO_WI_READ") ?? "";

    // ── Cache dir ────────────────────────────────────────────────────────
    public string DataDir { get; } = ResolveDataDir();

    // ── Feature flags ────────────────────────────────────────────────────
    public bool PreloadEmbeddings { get; } =
        Env("KG_PRELOAD_EMBEDDINGS") is "1" or "true" or "yes";

    public bool AggressiveEmbedding { get; } =
        Env("KG_AGGRESSIVE_EMBEDDING") is "1" or "true" or "yes";

    // ── Singleton ────────────────────────────────────────────────────────
    public static readonly AppSettings Default = new();

    // ── Helpers ──────────────────────────────────────────────────────────
    private static string? Env(string name) =>
        Environment.GetEnvironmentVariable(name) is { Length: > 0 } v ? v : null;

    private static string ResolveDataDir()
    {
        var kg = Env("KG_CACHE_DIR");
        if (kg is not null) return kg;
        var data = Env("DATA_DIR");
        if (data is not null) return data;
        return Path.Combine(AppContext.BaseDirectory, "data");
    }
}
