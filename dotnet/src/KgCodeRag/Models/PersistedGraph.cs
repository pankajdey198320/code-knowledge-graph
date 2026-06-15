namespace KgCodeRag.Models;

/// <summary>
/// Flat JSON-serialisable wrapper for a KnowledgeGraph + its metadata.
/// Replaces the Python pickle format with portable JSON.
/// </summary>
public sealed class PersistedGraph
{
    public GraphMetadata Metadata { get; set; } = new();
    /// <summary>Flat entity list (deserialized into KnowledgeGraph via <see cref="Restore"/>).</summary>
    public List<Entity> Entities { get; set; } = [];
    /// <summary>Flat relation list.</summary>
    public List<Relation> Relations { get; set; } = [];

    public static PersistedGraph From(KnowledgeGraph kg, GraphMetadata metadata) => new()
    {
        Metadata = metadata,
        Entities = [.. kg.Entities],
        Relations = [.. kg.Relations],
    };

    public (KnowledgeGraph Graph, GraphMetadata Metadata) Restore()
    {
        var graph = KnowledgeGraph.FromLists(Entities, Relations);
        return (graph, Metadata);
    }
}
