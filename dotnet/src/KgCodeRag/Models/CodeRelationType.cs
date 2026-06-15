namespace KgCodeRag.Models;

/// <summary>Directed-edge types in the code knowledge graph.</summary>
public enum CodeRelationType
{
    // Code structure
    Defines,        // file/class → symbol it defines
    Contains,       // class → method, namespace → class
    Calls,          // function → function
    Imports,        // file → module / symbol
    Inherits,       // class → base class
    Implements,     // class → interface
    UsesType,       // function → type (param / return)
    Overrides,      // method → base method
    DependsOn,      // file → file
    BelongsTo,      // symbol → namespace / module
    // Git-history relations
    ModifiedBy,     // file → author (weighted by commit count)
    CommittedIn,    // file → commit
    CoChanged,      // file ↔ file (same-commit co-occurrence)
    LinkedTo,       // commit → work_item
}
