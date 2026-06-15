using KgCodeRag.Models;

namespace KgCodeRag.Parsers;

/// <summary>Contract for language-specific AST walkers.</summary>
public interface ICodeParser
{
    /// <summary>Source language identifier returned on extracted entities (e.g. "csharp", "python").</summary>
    string Language { get; }

    /// <summary>
    /// Parse <paramref name="filePath"/> and return a sub-graph of entities + relations.
    /// The file path is made relative to <paramref name="repoRoot"/> in all entity records.
    /// Never throws — callers should catch and log.
    /// </summary>
    KnowledgeGraph ParseFile(string filePath, string repoRoot);
}
