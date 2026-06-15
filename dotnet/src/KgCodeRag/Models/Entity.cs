namespace KgCodeRag.Models;

/// <summary>A node in the code knowledge graph.</summary>
public sealed class Entity
{
    public string Name { get; init; } = "";
    public CodeEntityType EntityType { get; init; } = CodeEntityType.File;
    /// <summary>Source language: "csharp", "python", "cpp", etc.</summary>
    public string Language { get; init; } = "";
    /// <summary>Relative path inside the repo root.</summary>
    public string FilePath { get; init; } = "";
    public int LineStart { get; init; }
    public int LineEnd { get; init; }
    /// <summary>Function/method signature or class header.</summary>
    public string Signature { get; init; } = "";
    /// <summary>XML doc-comment summary or Python docstring.</summary>
    public string Docstring { get; init; } = "";
    /// <summary>Extensible metadata: commit sha, email, work-item ID, etc.</summary>
    public Dictionary<string, string> Metadata { get; init; } = new();

    /// <summary>Unique deduplication key: "{filePath}::{name}@{lineStart}"</summary>
    public string QualifiedKey => $"{FilePath}::{Name}@{LineStart}";

    public override string ToString() =>
        $"[{EntityType}] {Name} ({FilePath}:{LineStart})";
}
