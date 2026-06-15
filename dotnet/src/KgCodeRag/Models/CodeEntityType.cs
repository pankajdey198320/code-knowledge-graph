namespace KgCodeRag.Models;

/// <summary>Entity types for source-code knowledge graph nodes.</summary>
public enum CodeEntityType
{
    // Code structure
    File,
    Module,
    Namespace,
    Class,
    Struct,
    Interface,
    Enum,
    Function,
    Method,
    Property,
    Variable,
    Parameter,
    Import,
    Package,
    // Git-history entities
    Commit,
    Author,
    WorkItem,
}
