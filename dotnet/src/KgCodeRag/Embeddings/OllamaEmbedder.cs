using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using KgCodeRag.Models;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace KgCodeRag.Embeddings;

/// <summary>
/// Generates and caches text embeddings via Ollama's <c>/api/embeddings</c> endpoint.
/// Mirrors the Python <c>KGEmbedder</c> class.
///
/// Default model: <c>nomic-embed-text</c> (configurable via EMBEDDING_MODEL env var).
/// </summary>
public sealed class OllamaEmbedder : IDisposable
{
    private readonly HttpClient _http;
    private readonly string _model;
    private readonly string _baseUrl;
    private readonly ILogger<OllamaEmbedder> _logger;

    /// <summary>In-memory embedding cache keyed by entity <see cref="Entity.QualifiedKey"/>.</summary>
    private readonly Dictionary<string, float[]> _cache = new();

    /// <summary>Entity types skipped during batch embedding (low-value for semantic search).</summary>
    public static readonly HashSet<CodeEntityType> DefaultSkipTypes = new()
    {
        CodeEntityType.File,
        CodeEntityType.Import,
        CodeEntityType.Variable,
    };

    /// <summary>Aggressive skip — useful for very large codebases.</summary>
    public static readonly HashSet<CodeEntityType> AggressiveSkipTypes = new()
    {
        CodeEntityType.File,
        CodeEntityType.Import,
        CodeEntityType.Variable,
        CodeEntityType.Method,
        CodeEntityType.Property,
        CodeEntityType.Enum,
        CodeEntityType.Struct,
    };

    public OllamaEmbedder(
        string? baseUrl = null,
        string? model = null,
        ILogger<OllamaEmbedder>? logger = null)
    {
        _baseUrl = (baseUrl ?? Config.AppSettings.Default.OllamaBaseUrl).TrimEnd('/');
        _model = model ?? Config.AppSettings.Default.EmbeddingModel;
        _logger = logger ?? NullLogger<OllamaEmbedder>.Instance;
        _http = new HttpClient { Timeout = TimeSpan.FromMinutes(2) };
    }

    // ── Embedding generation ──────────────────────────────────────────────

    /// <summary>
    /// Embed a single text string via Ollama.  Returns an empty array on failure.
    /// </summary>
    public async Task<float[]> EmbedAsync(string text, CancellationToken ct = default)
    {
        try
        {
            var request = new EmbedRequest { Model = _model, Prompt = text };
            var response = await _http.PostAsJsonAsync($"{_baseUrl}/api/embeddings", request, ct);
            response.EnsureSuccessStatusCode();
            var result = await response.Content.ReadFromJsonAsync<EmbedResponse>(cancellationToken: ct);
            return result?.Embedding ?? [];
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Embedding failed for '{Text}': {Error}", text[..Math.Min(50, text.Length)], ex.Message);
            return [];
        }
    }

    /// <summary>
    /// Batch-embed all entities in <paramref name="kg"/> that are not in the skip set.
    /// Results are stored in <see cref="Cache"/>.
    /// </summary>
    public async Task EmbedGraphAsync(
        KnowledgeGraph kg,
        HashSet<CodeEntityType>? skipTypes = null,
        IProgress<(int done, int total)>? progress = null,
        CancellationToken ct = default)
    {
        skipTypes ??= DefaultSkipTypes;
        var entities = kg.Entities.Where(e => !skipTypes.Contains(e.EntityType)).ToList();
        var total = entities.Count;

        for (var i = 0; i < total; i++)
        {
            ct.ThrowIfCancellationRequested();
            var ent = entities[i];
            var key = ent.QualifiedKey;
            if (_cache.ContainsKey(key)) continue;

            var text = BuildEntityText(ent);
            var vec = await EmbedAsync(text, ct);
            if (vec.Length > 0) _cache[key] = vec;

            progress?.Report((i + 1, total));
        }
    }

    // ── Cache persistence ─────────────────────────────────────────────────

    public void SaveCache(string cachePath)
    {
        var dir = Path.GetDirectoryName(cachePath);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
        File.WriteAllText(cachePath, JsonSerializer.Serialize(_cache));
    }

    public bool LoadCache(string cachePath)
    {
        if (!File.Exists(cachePath)) return false;
        try
        {
            var loaded = JsonSerializer.Deserialize<Dictionary<string, float[]>>(File.ReadAllText(cachePath));
            if (loaded is null) return false;
            foreach (var (k, v) in loaded) _cache[k] = v;
            _logger.LogInformation("Loaded {Count} cached embeddings from {Path}", loaded.Count, cachePath);
            return true;
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not load embedding cache {Path}: {Error}", cachePath, ex.Message);
            return false;
        }
    }

    // ── Similarity search ─────────────────────────────────────────────────

    /// <summary>
    /// Find the <paramref name="topK"/> entities most similar to <paramref name="queryVec"/>.
    /// </summary>
    public List<(string EntityKey, float Score)> FindSimilar(float[] queryVec, int topK = 10)
    {
        if (_cache.Count == 0 || queryVec.Length == 0) return [];

        return _cache
            .Select(kv => (kv.Key, Score: CosineSimilarity(queryVec, kv.Value)))
            .OrderByDescending(x => x.Score)
            .Take(topK)
            .ToList();
    }

    /// <summary>Embed a query string and then call <see cref="FindSimilar"/>.</summary>
    public async Task<List<(string EntityKey, float Score)>> FindSimilarAsync(
        string query, int topK = 10, CancellationToken ct = default)
    {
        var vec = await EmbedAsync(query, ct);
        return FindSimilar(vec, topK);
    }

    // ── Utilities ─────────────────────────────────────────────────────────

    public IReadOnlyDictionary<string, float[]> Cache => _cache;

    /// <summary>Builds the natural-language text used to embed an entity.</summary>
    public static string BuildEntityText(Entity e)
    {
        var parts = new List<string>
        {
            $"{e.EntityType}: {e.Name}",
        };
        if (!string.IsNullOrWhiteSpace(e.Signature)) parts.Add($"signature: {e.Signature}");
        if (!string.IsNullOrWhiteSpace(e.Docstring)) parts.Add(e.Docstring);
        if (!string.IsNullOrWhiteSpace(e.FilePath)) parts.Add($"in {e.FilePath}");
        return string.Join(" ", parts);
    }

    public static float CosineSimilarity(float[] a, float[] b)
    {
        if (a.Length != b.Length || a.Length == 0) return 0f;
        float dot = 0, magA = 0, magB = 0;
        for (var i = 0; i < a.Length; i++)
        {
            dot += a[i] * b[i];
            magA += a[i] * a[i];
            magB += b[i] * b[i];
        }
        var denom = MathF.Sqrt(magA) * MathF.Sqrt(magB);
        return denom == 0 ? 0f : dot / denom;
    }

    public void Dispose() => _http.Dispose();

    // ── JSON DTOs ─────────────────────────────────────────────────────────

    private sealed class EmbedRequest
    {
        [JsonPropertyName("model")] public string Model { get; init; } = "";
        [JsonPropertyName("prompt")] public string Prompt { get; init; } = "";
    }

    private sealed class EmbedResponse
    {
        [JsonPropertyName("embedding")] public float[]? Embedding { get; init; }
    }
}
