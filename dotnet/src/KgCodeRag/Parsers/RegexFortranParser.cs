using System.Text.RegularExpressions;
using KgCodeRag.Models;

namespace KgCodeRag.Parsers;

/// <summary>
/// Regex-based Fortran parser (MVP).
/// Supports fixed-form (.f .for) and free-form (.f90 .f95 .f03 .f08 .fpp) Fortran.
///
/// Extracts:
///   - MODULE / END MODULE                 → CodeEntityType.Module
///   - SUBROUTINE name(params)             → CodeEntityType.Function (DEFINES / CONTAINS)
///   - FUNCTION name(params)               → CodeEntityType.Function (DEFINES / CONTAINS)
///   - USE module_name                     → CodeEntityType.Import + IMPORTS relation
///   - INCLUDE 'file'                      → CodeEntityType.Import + IMPORTS relation
///   - CALL name(args)                     → CALLS relation
///   - BIND(C [, NAME='cname'])            → interop metadata on subroutines/functions
/// </summary>
public sealed class RegexFortranParser : ICodeParser
{
    public string Language => "fortran";

    // All Fortran matching is case-insensitive
    private const RegexOptions Ri = RegexOptions.IgnoreCase | RegexOptions.Compiled;

    // ── Patterns ─────────────────────────────────────────────────────────────

    // MODULE Foo  (but not MODULE PROCEDURE)
    private static readonly Regex ModuleStartRe = new(
        @"^\s*MODULE\s+(?!PROCEDURE\b)(?<name>\w+)\s*$", Ri);

    // END MODULE [name]
    private static readonly Regex ModuleEndRe = new(
        @"^\s*END\s+MODULE\b", Ri);

    // SUBROUTINE name(params) [BIND(C [, NAME='c_name'])]
    private static readonly Regex SubroutineRe = new(
        @"^\s*(?:PURE\s+|ELEMENTAL\s+|RECURSIVE\s+)?SUBROUTINE\s+(?<name>\w+)\s*(?:\([^)]*\))?\s*(?<bind>BIND\s*\([^)]*\))?",
        Ri);

    // END SUBROUTINE [name]
    private static readonly Regex SubroutineEndRe = new(
        @"^\s*END\s+SUBROUTINE\b", Ri);

    // FUNCTION name(params) [RESULT(r)] [BIND(C [, NAME='c_name'])]
    private static readonly Regex FunctionRe = new(
        @"^\s*(?:(?:PURE|ELEMENTAL|RECURSIVE|[\w*()]+)\s+)*FUNCTION\s+(?<name>\w+)\s*(?:\([^)]*\))?\s*(?:RESULT\s*\(\w+\)\s*)?(?<bind>BIND\s*\([^)]*\))?",
        Ri);

    // END FUNCTION [name]
    private static readonly Regex FunctionEndRe = new(
        @"^\s*END\s+FUNCTION\b", Ri);

    // USE module_name [, ONLY: ...]
    private static readonly Regex UseRe = new(
        @"^\s*USE\s+(?:,\s*\w+\s*::\s*)?(?<name>\w+)", Ri);

    // INCLUDE 'file' or INCLUDE "file"
    private static readonly Regex IncludeRe = new(
        @"^\s*INCLUDE\s+['""](?<file>[^'""]+)['""]", Ri);

    // CALL name(...)
    private static readonly Regex CallRe = new(
        @"^\s*CALL\s+(?<name>[\w%]+)\s*(?:\(|$)", Ri);

    // Function-call expression inside an expression: name(
    private static readonly Regex CallExprRe = new(
        @"(?<!['""\w])(\w[\w%]*)[ \t]*\(", RegexOptions.Compiled);

    // Extract BIND(C, NAME='cname') — the NAME= part
    private static readonly Regex BindNameRe = new(
        @"NAME\s*=\s*['""](?<n>[^'""]+)['""]", Ri);

    // ── Entry point ──────────────────────────────────────────────────────────

    public KnowledgeGraph ParseFile(string filePath, string repoRoot)
    {
        var source = File.ReadAllText(filePath);
        var relPath = Path.GetRelativePath(repoRoot, filePath).Replace('\\', '/');
        var lines = source.Split('\n');

        var kg = new KnowledgeGraph();

        var fileEnt = new Entity
        {
            Name = relPath,
            EntityType = CodeEntityType.File,
            Language = Language,
            FilePath = relPath,
            LineStart = 1,
            LineEnd = lines.Length,
        };
        kg.AddEntity(fileEnt);

        // Context stack: (entityKey, entityType, moduleName)
        // moduleName is propagated to subroutines/functions to qualify their names
        var ctxStack = new Stack<(string Key, CodeEntityType Type, string ModuleName)>();
        ctxStack.Push((fileEnt.QualifiedKey, CodeEntityType.File, ""));

        for (var i = 0; i < lines.Length; i++)
        {
            var raw = lines[i];
            var line = StripFortranComment(raw);
            var trimmed = line.Trim();
            var lineNo = i + 1;

            if (string.IsNullOrWhiteSpace(trimmed)) continue;

            var top = ctxStack.Peek();

            // ── END MODULE / SUBROUTINE / FUNCTION (pop context) ─────────
            if (ModuleEndRe.IsMatch(trimmed))
            {
                PopUntil(ctxStack, CodeEntityType.Module);
                continue;
            }
            if (SubroutineEndRe.IsMatch(trimmed) || FunctionEndRe.IsMatch(trimmed))
            {
                PopUntil(ctxStack, CodeEntityType.Function);
                continue;
            }

            // ── MODULE ────────────────────────────────────────────────────
            var m = ModuleStartRe.Match(trimmed);
            if (m.Success)
            {
                var modName = m.Groups["name"].Value;
                var ent = Make(modName, CodeEntityType.Module, relPath, lineNo, null);
                kg.AddEntity(ent);
                kg.AddRelation(new Relation(top.Key, ent.QualifiedKey, CodeRelationType.Defines));
                ctxStack.Push((ent.QualifiedKey, CodeEntityType.Module, modName));
                continue;
            }

            // ── SUBROUTINE ────────────────────────────────────────────────
            m = SubroutineRe.Match(trimmed);
            if (m.Success)
            {
                var subName = m.Groups["name"].Value;
                var bindStr = m.Groups["bind"].Value;
                var qualName = QualifiedName(subName, top.ModuleName);
                var sig = trimmed;

                var metadata = ExtractBindMetadata(bindStr, subName);
                var ent = Make(qualName, CodeEntityType.Function, relPath, lineNo, sig, metadata);
                kg.AddEntity(ent);

                var relType = top.Type == CodeEntityType.Module
                    ? CodeRelationType.Contains
                    : CodeRelationType.Defines;
                kg.AddRelation(new Relation(top.Key, ent.QualifiedKey, relType));

                if (metadata.TryGetValue("bind_c", out var cName))
                    kg.AddRelation(new Relation(ent.QualifiedKey, cName,
                        CodeRelationType.Calls, new Dictionary<string, string> { ["interop"] = "bind_c" }));

                ctxStack.Push((ent.QualifiedKey, CodeEntityType.Function, top.ModuleName));
                continue;
            }

            // ── FUNCTION ──────────────────────────────────────────────────
            m = FunctionRe.Match(trimmed);
            if (m.Success)
            {
                var funcName = m.Groups["name"].Value;
                var bindStr = m.Groups["bind"].Value;
                var qualName = QualifiedName(funcName, top.ModuleName);
                var sig = trimmed;

                var metadata = ExtractBindMetadata(bindStr, funcName);
                var ent = Make(qualName, CodeEntityType.Function, relPath, lineNo, sig, metadata);
                kg.AddEntity(ent);

                var relType = top.Type == CodeEntityType.Module
                    ? CodeRelationType.Contains
                    : CodeRelationType.Defines;
                kg.AddRelation(new Relation(top.Key, ent.QualifiedKey, relType));

                if (metadata.TryGetValue("bind_c", out var cName))
                    kg.AddRelation(new Relation(ent.QualifiedKey, cName,
                        CodeRelationType.Calls, new Dictionary<string, string> { ["interop"] = "bind_c" }));

                ctxStack.Push((ent.QualifiedKey, CodeEntityType.Function, top.ModuleName));
                continue;
            }

            // ── USE (module import) ───────────────────────────────────────
            m = UseRe.Match(trimmed);
            if (m.Success)
            {
                var modName = m.Groups["name"].Value;
                var ent = Make(modName, CodeEntityType.Import, relPath, lineNo, trimmed);
                kg.AddEntity(ent);
                kg.AddRelation(new Relation(top.Key, ent.QualifiedKey, CodeRelationType.Imports));
                kg.AddRelation(new Relation(top.Key, modName, CodeRelationType.Imports));
                continue;
            }

            // ── INCLUDE ───────────────────────────────────────────────────
            m = IncludeRe.Match(trimmed);
            if (m.Success)
            {
                var file = m.Groups["file"].Value;
                var ent = Make(file, CodeEntityType.Import, relPath, lineNo, trimmed);
                kg.AddEntity(ent);
                kg.AddRelation(new Relation(top.Key, ent.QualifiedKey, CodeRelationType.Imports));
                continue;
            }

            // ── CALL statement ────────────────────────────────────────────
            if (top.Type == CodeEntityType.Function)
            {
                m = CallRe.Match(trimmed);
                if (m.Success)
                {
                    var callee = m.Groups["name"].Value;
                    kg.AddRelation(new Relation(top.Key, callee, CodeRelationType.Calls));
                    continue;
                }

                // Function-call expressions (RHS of assignments, array constructors, etc.)
                foreach (Match cm in CallExprRe.Matches(trimmed))
                {
                    var callee = cm.Groups[1].Value;
                    if (!FortranKeywords.Contains(callee.ToUpperInvariant()))
                        kg.AddRelation(new Relation(top.Key, callee, CodeRelationType.Calls));
                }
            }
        }

        return kg;
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    private Entity Make(
        string name, CodeEntityType type, string relPath, int lineNo, string? sig,
        Dictionary<string, string>? metadata = null) =>
        new()
        {
            Name = name,
            EntityType = type,
            Language = Language,
            FilePath = relPath,
            LineStart = lineNo,
            LineEnd = lineNo,
            Signature = sig ?? "",
            Metadata = metadata ?? [],
        };

    private static string QualifiedName(string name, string moduleName) =>
        string.IsNullOrEmpty(moduleName) ? name : $"{moduleName}::{name}";

    private Dictionary<string, string> ExtractBindMetadata(string bindStr, string fortranName)
    {
        if (string.IsNullOrWhiteSpace(bindStr)) return [];

        var m = BindNameRe.Match(bindStr);
        var cName = m.Success ? m.Groups["n"].Value : fortranName.ToLowerInvariant();
        return new Dictionary<string, string> { ["bind_c"] = cName };
    }

    private static void PopUntil(
        Stack<(string Key, CodeEntityType Type, string ModuleName)> stack,
        CodeEntityType target)
    {
        while (stack.Count > 1 && stack.Peek().Type != target)
            stack.Pop();
        if (stack.Count > 1)
            stack.Pop(); // pop the target itself
    }

    /// <summary>
    /// Strip Fortran inline comments.
    /// Free-form: ! starts a comment.
    /// Fixed-form: C or * in column 1 marks a full-line comment (handled by blank check).
    /// </summary>
    private static string StripFortranComment(string line)
    {
        // Fixed-form: comment line (C or * in col 1)
        if (line.Length > 0 && (line[0] == 'C' || line[0] == 'c' || line[0] == '*'))
            return string.Empty;

        // Free-form: ! comment
        var idx = line.IndexOf('!');
        return idx >= 0 ? line[..idx] : line;
    }

    private static readonly HashSet<string> FortranKeywords = new(StringComparer.OrdinalIgnoreCase)
    {
        "IF", "ELSE", "ELSEIF", "ENDIF", "END", "DO", "ENDDO", "WHILE",
        "SELECT", "CASE", "ENDSELECT", "RETURN", "STOP", "EXIT", "CYCLE",
        "GOTO", "WRITE", "READ", "PRINT", "OPEN", "CLOSE", "FLUSH",
        "ALLOCATE", "DEALLOCATE", "NULLIFY", "ASSOCIATED", "ALLOCATED",
        "PRESENT", "SIZE", "SHAPE", "LBOUND", "UBOUND", "TRIM", "LEN",
        "LEN_TRIM", "ADJUSTL", "ADJUSTR", "INDEX", "SCAN", "VERIFY",
        "ABS", "SQRT", "EXP", "LOG", "SIN", "COS", "TAN", "ASIN",
        "ACOS", "ATAN", "ATAN2", "MAX", "MIN", "MOD", "MODULO",
        "REAL", "INT", "DBLE", "CMPLX", "AIMAG", "CONJG",
        "MERGE", "PACK", "UNPACK", "SPREAD", "RESHAPE", "TRANSPOSE",
        "MATMUL", "DOT_PRODUCT", "SUM", "PRODUCT", "COUNT", "ANY", "ALL",
        "MAXVAL", "MINVAL", "MAXLOC", "MINLOC",
        "NEW_LINE", "CHAR", "ICHAR", "IACHAR", "ACHAR",
        "DATE_AND_TIME", "SYSTEM_CLOCK", "CPU_TIME",
        "TRANSFER", "BIT_SIZE", "IAND", "IOR", "IEOR", "ISHFT", "IBITS",
    };
}
