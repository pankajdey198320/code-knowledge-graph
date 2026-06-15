namespace KgCodeRag.Models;

/// <summary>
/// In-memory code knowledge graph with O(1) entity lookup and fast BFS traversal.
/// Thread-safe for concurrent reads; mutations must be externally synchronised.
/// </summary>
public sealed class KnowledgeGraph
{
    private readonly Dictionary<string, Entity> _entityMap = new();
    private readonly List<Entity> _entities = new();
    private readonly List<Relation> _relations = new();
    // Adjacency: entity key → all incident relations (in or out)
    private readonly Dictionary<string, List<Relation>> _adjacency = new();

    public IReadOnlyList<Entity> Entities => _entities;
    public IReadOnlyList<Relation> Relations => _relations;

    // ── Mutation ──────────────────────────────────────────────────────────

    public void AddEntity(Entity entity)
    {
        var key = entity.QualifiedKey;
        if (_entityMap.TryAdd(key, entity))
            _entities.Add(entity);
    }

    public void AddRelation(Relation relation)
    {
        _relations.Add(relation);

        if (!_adjacency.TryGetValue(relation.Source, out var srcList))
            _adjacency[relation.Source] = srcList = [];
        srcList.Add(relation);

        if (!_adjacency.TryGetValue(relation.Target, out var tgtList))
            _adjacency[relation.Target] = tgtList = [];
        tgtList.Add(relation);
    }

    public void MergeFrom(KnowledgeGraph other)
    {
        foreach (var e in other.Entities) AddEntity(e);
        foreach (var r in other.Relations) AddRelation(r);
    }

    // ── Query ─────────────────────────────────────────────────────────────

    public Entity? GetEntity(string key) => _entityMap.GetValueOrDefault(key);

    /// <summary>Filter entities by any combination of name substring, type, and file path suffix.</summary>
    public List<Entity> FindEntities(
        string? name = null,
        CodeEntityType? entityType = null,
        string? filePath = null)
    {
        IEnumerable<Entity> results = _entities;

        if (name is not null)
            results = results.Where(e => e.Name.Contains(name, StringComparison.OrdinalIgnoreCase));

        if (entityType.HasValue)
            results = results.Where(e => e.EntityType == entityType.Value);

        if (filePath is not null)
        {
            var fp = filePath.Replace('\\', '/');
            results = results.Where(e =>
                e.FilePath.Replace('\\', '/').Contains(fp, StringComparison.OrdinalIgnoreCase));
        }

        return results.ToList();
    }

    /// <summary>BFS over incident relations up to <paramref name="hops"/> hops from <paramref name="entityKey"/>.</summary>
    public List<Relation> GetNeighbors(string entityKey, int hops = 1)
    {
        var visited = new HashSet<string> { entityKey };
        var frontier = new HashSet<string> { entityKey };
        var result = new List<Relation>();

        for (var i = 0; i < hops; i++)
        {
            var nextFrontier = new HashSet<string>();
            foreach (var key in frontier)
            {
                if (!_adjacency.TryGetValue(key, out var rels)) continue;
                foreach (var rel in rels)
                {
                    result.Add(rel);
                    var other = rel.Source == key ? rel.Target : rel.Source;
                    if (visited.Add(other))
                        nextFrontier.Add(other);
                }
            }
            frontier = nextFrontier;
            if (frontier.Count == 0) break;
        }
        return result;
    }

    // ── Serialisation helpers ─────────────────────────────────────────────

    /// <summary>Reconstruct a KnowledgeGraph from flat entity + relation lists (JSON load path).</summary>
    public static KnowledgeGraph FromLists(IEnumerable<Entity> entities, IEnumerable<Relation> relations)
    {
        var kg = new KnowledgeGraph();
        foreach (var e in entities) kg.AddEntity(e);
        foreach (var r in relations) kg.AddRelation(r);
        return kg;
    }
}
