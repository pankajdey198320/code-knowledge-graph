namespace KgCodeRag.Models;

/// <summary>A directed edge between two code entities.</summary>
public sealed class Relation
{
    public Relation() { }

    public Relation(string source, string target, CodeRelationType relationType,
        Dictionary<string, string>? metadata = null)
    {
        Source = source;
        Target = target;
        RelationType = relationType;
        if (metadata is not null) Metadata = metadata;
    }

    /// <summary>Source entity QualifiedKey or name.</summary>
    public string Source { get; init; } = "";
    /// <summary>Target entity QualifiedKey or name.</summary>
    public string Target { get; init; } = "";
    public CodeRelationType RelationType { get; init; } = CodeRelationType.DependsOn;
    /// <summary>Optional edge metadata, e.g. commit_count, co_change_count.</summary>
    public Dictionary<string, string> Metadata { get; init; } = new();
}
