using System.Text.RegularExpressions;
using KgCodeRag.Models;

namespace KgCodeRag.Parsers;

/// <summary>
/// Regex-based C++ / C parser (MVP).
/// Extracts: #include directives, namespaces, classes, structs, enums,
/// function/method definitions (single-line and Allman-brace style),
/// inheritance, and call expressions.
///
/// Supports .cpp .cc .cxx .c .h .hpp .hxx
/// </summary>
public sealed class RegexCppParser : ICodeParser
{
    public string Language => "cpp";

    // ── Patterns ────────────────────────────────────────────────────────────

    // #include <file> or #include "file"
    private static readonly Regex IncludeRe = new(
        @"^\s*#\s*include\s*[""<]([^"">]+)[>""]",
        RegexOptions.Compiled);

    // namespace Foo { or namespace Foo::Bar {
    private static readonly Regex NamespaceRe = new(
        @"^\s*namespace\s+([\w:]+)\s*(?:\{|$)",
        RegexOptions.Compiled);

    // class/struct Foo [final] [: public Bar, private Baz] {
    private static readonly Regex ClassRe = new(
        @"^\s*(?:template\s*<[^>]*>\s*)?(?<kw>class|struct)\s+(?<name>\w+)\s*(?:final\s*)?(?::\s*(?<bases>[^{;]+?))?\s*\{",
        RegexOptions.Compiled);

    // class/struct Foo ... (without {, for Allman style)
    private static readonly Regex ClassSigRe = new(
        @"^\s*(?:template\s*<[^>]*>\s*)?(?<kw>class|struct)\s+(?<name>\w+)\s*(?:final\s*)?(?::\s*(?<bases>[^{;]+?))?\s*$",
        RegexOptions.Compiled);

    // enum [class] Foo [: type] {
    private static readonly Regex EnumRe = new(
        @"^\s*enum\s+(?:class\s+)?(?<name>\w+)\s*(?::\s*[\w:]+\s*)?\{",
        RegexOptions.Compiled);

    // Function/method with opening brace on the same line
    private static readonly Regex FuncDefRe = new(
        @"^\s*(?:(?:virtual|static|inline|explicit|constexpr|friend|extern)\s+)*[\w:*&<>\[\]]+(?:\s+[\w:*&<>\[\]]+)*\s+(?<name>[\w:~]+)\s*\([^)]*\)\s*(?:const\s*)?(?:noexcept(?:\s*\([^)]*\))?\s*)?(?:override\s*)?(?:final\s*)?(?:->\s*[\w:*&<>]+\s*)?\{",
        RegexOptions.Compiled);

    // Function/method signature WITHOUT opening brace (Allman brace style)
    private static readonly Regex FuncSigRe = new(
        @"^\s*(?:(?:virtual|static|inline|explicit|constexpr|friend|extern)\s+)*[\w:*&<>\[\]]+(?:\s+[\w:*&<>\[\]]+)*\s+(?<name>[\w:~]+)\s*\([^)]*\)\s*(?:const\s*)?(?:noexcept(?:\s*\([^)]*\))?\s*)?(?:override\s*)?(?:final\s*)?(?:->\s*[\w:*&<>]+\s*)?$",
        RegexOptions.Compiled);

    // Opening brace on its own line
    private static readonly Regex OpenBraceOnlyRe = new(
        @"^\s*\{\s*$",
        RegexOptions.Compiled);

    // Call expression inside a function body: name(
    private static readonly Regex CallRe = new(
        @"(?<![""'\w.])(\w[\w:]*)[ \t]*\(",
        RegexOptions.Compiled);

    // Base class: "public Foo" or "private Bar::Baz"
    private static readonly Regex BaseRe = new(
        @"(?:public|protected|private)\s+([\w:]+)",
        RegexOptions.Compiled);

    private static readonly HashSet<string> Keywords = new(StringComparer.Ordinal)
    {
        "if", "else", "for", "while", "do", "switch", "case", "return", "break",
        "continue", "goto", "try", "catch", "throw", "new", "delete", "sizeof",
        "alignof", "decltype", "typeid", "operator", "namespace", "class", "struct",
        "enum", "template", "typedef", "using", "public", "protected", "private",
        "virtual", "override", "final", "explicit", "inline", "static", "extern",
        "const", "constexpr", "volatile", "mutable", "auto", "void", "bool",
        "int", "long", "short", "char", "float", "double", "unsigned", "signed",
        "true", "false", "nullptr", "this", "co_await", "co_return", "co_yield",
        "assert", "NULL", "BOOL", "DWORD", "HANDLE",
    };

    // ── Entry point ─────────────────────────────────────────────────────────

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

        // Stack: (entityKey, entityType, braceDepthWhenOpened)
        // braceDepthWhenOpened = depth AFTER the opening '{' of this block
        var ctxStack = new Stack<(string Key, CodeEntityType Type, int OpenDepth)>();
        ctxStack.Push((fileEnt.QualifiedKey, CodeEntityType.File, 0));

        var depth = 0;

        // Pending: when we detect a class/function signature WITHOUT { on the same line
        // we remember it so the next standalone { line activates it
        string? pendingKey = null;
        var pendingType = CodeEntityType.File; // sentinel default

        for (var i = 0; i < lines.Length; i++)
        {
            var raw = lines[i];
            var line = StripLineComment(raw);
            var trimmed = line.TrimStart();
            var lineNo = i + 1;

            if (string.IsNullOrWhiteSpace(trimmed))
            {
                ApplyBraces(line, ref depth, ref pendingKey, ref pendingType, ctxStack);
                continue;
            }

            // ── Activate pending context when we hit a standalone { ────────
            if (pendingKey is not null && OpenBraceOnlyRe.IsMatch(trimmed))
            {
                depth++;
                ctxStack.Push((pendingKey, pendingType, depth));
                pendingKey = null;
                continue;
            }
            else if (pendingKey is not null && !trimmed.StartsWith("{"))
            {
                // Signature was a declaration (followed by something other than {)
                pendingKey = null;
            }

            var top = ctxStack.Peek();

            // ── #include ──────────────────────────────────────────────────
            var m = IncludeRe.Match(trimmed);
            if (m.Success)
            {
                var importName = $"#include <{m.Groups[1].Value}>";
                var ent = Make(importName, CodeEntityType.Import, relPath, lineNo, trimmed.Trim());
                kg.AddEntity(ent);
                kg.AddRelation(new Relation(top.Key, ent.QualifiedKey, CodeRelationType.Imports));
                ApplyBraces(line, ref depth, ref pendingKey, ref pendingType, ctxStack);
                continue;
            }

            // ── namespace ─────────────────────────────────────────────────
            m = NamespaceRe.Match(trimmed);
            if (m.Success)
            {
                var nsName = m.Groups[1].Value;
                var ent = Make(nsName, CodeEntityType.Namespace, relPath, lineNo, null);
                kg.AddEntity(ent);
                kg.AddRelation(new Relation(top.Key, ent.QualifiedKey, CodeRelationType.Defines));

                if (line.Contains('{'))
                {
                    ApplyBraces(line, ref depth, ref pendingKey, ref pendingType, ctxStack);
                    ctxStack.Push((ent.QualifiedKey, CodeEntityType.Namespace, depth));
                }
                else
                {
                    // Next { opens the namespace
                    pendingKey = ent.QualifiedKey;
                    pendingType = CodeEntityType.Namespace;
                    ApplyBraces(line, ref depth, ref pendingKey, ref pendingType, ctxStack);
                }
                continue;
            }

            // ── class / struct (same-line {) ─────────────────────────────
            m = ClassRe.Match(trimmed);
            if (m.Success)
            {
                var (ent, ok) = TryMakeClassEnt(m, relPath, lineNo, kg, top.Key);
                if (ok)
                {
                    ApplyBraces(line, ref depth, ref pendingKey, ref pendingType, ctxStack);
                    ctxStack.Push((ent!.QualifiedKey, ent.EntityType, depth));
                    continue;
                }
            }

            // ── class / struct (Allman — no { on this line) ───────────────
            m = ClassSigRe.Match(trimmed);
            if (m.Success && !trimmed.TrimEnd().EndsWith(';'))
            {
                var (ent, ok) = TryMakeClassEnt(m, relPath, lineNo, kg, top.Key);
                if (ok)
                {
                    pendingKey = ent!.QualifiedKey;
                    pendingType = ent.EntityType;
                    ApplyBraces(line, ref depth, ref pendingKey, ref pendingType, ctxStack);
                    continue;
                }
            }

            // ── enum ──────────────────────────────────────────────────────
            m = EnumRe.Match(trimmed);
            if (m.Success)
            {
                var enumName = m.Groups["name"].Value;
                var ent = Make(enumName, CodeEntityType.Enum, relPath, lineNo, null);
                kg.AddEntity(ent);
                kg.AddRelation(new Relation(top.Key, ent.QualifiedKey, CodeRelationType.Defines));
                ApplyBraces(line, ref depth, ref pendingKey, ref pendingType, ctxStack);
                ctxStack.Push((ent.QualifiedKey, CodeEntityType.Enum, depth));
                continue;
            }

            // ── function / method (same-line {) ───────────────────────────
            m = FuncDefRe.Match(trimmed);
            if (m.Success)
            {
                var funcName = m.Groups["name"].Value;
                if (!Keywords.Contains(funcName))
                {
                    var ent = MakeFuncEnt(funcName, top.Type, relPath, lineNo, trimmed, kg, top.Key);
                    ApplyBraces(line, ref depth, ref pendingKey, ref pendingType, ctxStack);
                    ctxStack.Push((ent.QualifiedKey, ent.EntityType, depth));
                    continue;
                }
            }

            // ── function / method (Allman — no { on this line) ────────────
            m = FuncSigRe.Match(trimmed);
            if (m.Success && !trimmed.TrimEnd().EndsWith(';') && !trimmed.Contains('='))
            {
                var funcName = m.Groups["name"].Value;
                if (!Keywords.Contains(funcName))
                {
                    var ent = MakeFuncEnt(funcName, top.Type, relPath, lineNo, trimmed, kg, top.Key);
                    pendingKey = ent.QualifiedKey;
                    pendingType = ent.EntityType;
                    ApplyBraces(line, ref depth, ref pendingKey, ref pendingType, ctxStack);
                    continue;
                }
            }

            // ── call expressions inside a function / method body ──────────
            if (top.Type is CodeEntityType.Function or CodeEntityType.Method)
            {
                foreach (Match cm in CallRe.Matches(trimmed))
                {
                    var callee = cm.Groups[1].Value;
                    if (!Keywords.Contains(callee) && callee.Length > 1)
                        kg.AddRelation(new Relation(top.Key, callee, CodeRelationType.Calls));
                }
            }

            ApplyBraces(line, ref depth, ref pendingKey, ref pendingType, ctxStack);
        }

        return kg;
    }

    // ── Helpers ─────────────────────────────────────────────────────────────

    private Entity Make(string name, CodeEntityType type, string relPath, int lineNo, string? sig) =>
        new()
        {
            Name = name,
            EntityType = type,
            Language = Language,
            FilePath = relPath,
            LineStart = lineNo,
            LineEnd = lineNo,
            Signature = sig ?? "",
        };

    private (Entity? ent, bool ok) TryMakeClassEnt(
        Match m, string relPath, int lineNo,
        KnowledgeGraph kg, string parentKey)
    {
        var clsName = m.Groups["name"].Value;
        if (Keywords.Contains(clsName)) return (null, false);

        var kw = m.Groups["kw"].Value;
        var basesStr = m.Groups["bases"].Value;
        var etype = kw == "struct" ? CodeEntityType.Struct : CodeEntityType.Class;

        var sig = m.Value.TrimEnd('{').Trim();
        var ent = Make(clsName, etype, relPath, lineNo, sig);
        kg.AddEntity(ent);
        kg.AddRelation(new Relation(parentKey, ent.QualifiedKey, CodeRelationType.Defines));

        foreach (Match bm in BaseRe.Matches(basesStr))
            kg.AddRelation(new Relation(ent.QualifiedKey, bm.Groups[1].Value, CodeRelationType.Inherits));

        return (ent, true);
    }

    private Entity MakeFuncEnt(
        string funcName, CodeEntityType parentType,
        string relPath, int lineNo, string sig,
        KnowledgeGraph kg, string parentKey)
    {
        var isMethod = parentType is CodeEntityType.Class or CodeEntityType.Struct;
        var etype = isMethod ? CodeEntityType.Method : CodeEntityType.Function;
        var relType = isMethod ? CodeRelationType.Contains : CodeRelationType.Defines;

        var ent = Make(funcName, etype, relPath, lineNo, sig.TrimEnd('{').Trim());
        kg.AddEntity(ent);
        kg.AddRelation(new Relation(parentKey, ent.QualifiedKey, relType));
        return ent;
    }

    private static void ApplyBraces(
        string line,
        ref int depth,
        ref string? pendingKey,
        ref CodeEntityType pendingType,
        Stack<(string Key, CodeEntityType Type, int OpenDepth)> ctxStack)
    {
        var inStr = false;
        var prev = '\0';
        foreach (var c in line)
        {
            if (c == '"' && prev != '\\') inStr = !inStr;
            if (!inStr)
            {
                if (c == '{')
                {
                    depth++;
                    // Activate a pending context (e.g. Allman class/func encountered mid-line)
                    if (pendingKey is not null)
                    {
                        ctxStack.Push((pendingKey, pendingType, depth));
                        pendingKey = null;
                    }
                }
                else if (c == '}')
                {
                    depth--;
                    while (ctxStack.Count > 1 && ctxStack.Peek().OpenDepth > depth)
                        ctxStack.Pop();
                }
            }
            prev = c;
        }
    }

    private static string StripLineComment(string line)
    {
        var idx = line.IndexOf("//", StringComparison.Ordinal);
        return idx >= 0 ? line[..idx] : line;
    }
}
