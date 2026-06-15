using KgCodeRag.Embeddings;
using KgCodeRag.Models;

namespace KgCodeRag.Retrieval;

/// <summary>
/// Semantic code retrieval: embed a query → cosine similarity → top-k seed entities
/// → BFS graph traversal (2 hops) → formatted Markdown subgraph.
/// Mirrors the Python <c>GraphRetriever</c> class.
/// </summary>
public sealed class GraphRetriever
{
    private readonly KnowledgeGraph _kg;
    private readonly OllamaEmbedder _embedder;

    public int TopK { get; }
    public int Hops { get; }

    public GraphRetriever(KnowledgeGraph kg, OllamaEmbedder embedder, int topK = 10, int hops = 2)
    {
        _kg = kg;
        _embedder = embedder;
        TopK = topK;
        Hops = hops;
    }

    // ── Retrieval modes ───────────────────────────────────────────────────

    /// <summary>Semantic similarity search followed by graph neighbourhood expansion.</summary>
    public async Task<RetrievalContext> RetrieveAsync(string query, CancellationToken ct = default)
    {
        var seeds = await _embedder.FindSimilarAsync(query, TopK, ct);
        var seedEntities = seeds
            .Select(s => _kg.GetEntity(s.EntityKey))
            .OfType<Entity>()
            .ToList();
        return BuildContext(seedEntities);
    }

    /// <summary>Exact-name lookup + neighbourhood.</summary>
    public RetrievalContext RetrieveByName(string name)
    {
        var seeds = _kg.FindEntities(name: name).Take(TopK).ToList();
        return BuildContext(seeds);
    }

    /// <summary>All entities in a specific file + their neighbours.</summary>
    public RetrievalContext RetrieveByFile(string filePath)
    {
        var seeds = _kg.FindEntities(filePath: filePath).Take(TopK).ToList();
        return BuildContext(seeds);
    }

    // ── Graph expansion ───────────────────────────────────────────────────

    private RetrievalContext BuildContext(List<Entity> seeds)
    {
        var entityKeys = new HashSet<string>(seeds.Select(e => e.QualifiedKey));
        var relationDedup = new HashSet<string>();
        var relations = new List<Relation>();

        foreach (var seed in seeds)
        {
            foreach (var rel in _kg.GetNeighbors(seed.QualifiedKey, Hops))
            {
                var dedupeKey = $"{rel.Source}|{rel.RelationType}|{rel.Target}";
                if (!relationDedup.Add(dedupeKey)) continue;
                relations.Add(rel);
                entityKeys.Add(rel.Source);
                entityKeys.Add(rel.Target);
            }
        }

        var entities = entityKeys
            .Select(k => _kg.GetEntity(k))
            .OfType<Entity>()
            .ToList();

        return new RetrievalContext(entities, relations, FormatSubgraph(entities, relations));
    }

    // ── Formatting ────────────────────────────────────────────────────────

    private static string FormatSubgraph(List<Entity> entities, List<Relation> relations)
    {
        var sb = new System.Text.StringBuilder();

        sb.AppendLine("## Entities");
        foreach (var e in entities.OrderBy(e => e.EntityType.ToString()).ThenBy(e => e.Name))
        {
            var loc = e.FilePath.Length > 0 ? $" ({e.FilePath}:{e.LineStart})" : "";
            var sig = e.Signature.Length > 0 ? $" — {e.Signature[..Math.Min(80, e.Signature.Length)]}" : "";
            sb.AppendLine($"- [{e.EntityType}] {e.Name}{loc}{sig}");
        }

        sb.AppendLine();
        sb.AppendLine("## Relations");
        foreach (var r in relations)
            sb.AppendLine($"- {r.Source} --[{r.RelationType}]--> {r.Target}");

        return sb.ToString();
    }
}

/// <summary>Result of a retrieval operation.</summary>
public sealed record RetrievalContext(
    List<Entity> Entities,
    List<Relation> Relations,
    string SubgraphText);
