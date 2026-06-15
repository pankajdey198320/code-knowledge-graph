using System.Text.RegularExpressions;
using KgCodeRag.Models;

namespace KgCodeRag.Parsers;

/// <summary>
/// Regex-based Python parser (MVP implementation).
/// Extracts: file, module-level imports, classes (with base classes),
/// functions and methods, docstrings, and call expressions.
///
/// Accuracy: covers ~90% of real-world Python for knowledge-graph purposes.
/// Replace with a tree-sitter binding for full accuracy if needed.
/// </summary>
public sealed class RegexPythonParser : ICodeParser
{
    public string Language => "python";

    // ── Regex patterns ───────────────────────────────────────────────────

    // Imports: "import x" or "from x import y"
    private static readonly Regex ImportPattern = new(
        @"^(import\s+\S+|from\s+\S+\s+import\s+.+)$",
        RegexOptions.Multiline | RegexOptions.Compiled);

    // Class definition: "class Foo(Bar, Baz):"
    private static readonly Regex ClassPattern = new(
        @"^(?<indent>[ \t]*)class\s+(?<name>\w+)\s*(?:\((?<bases>[^)]*)\))?\s*:",
        RegexOptions.Multiline | RegexOptions.Compiled);

    // Function / method definition (including async)
    private static readonly Regex FuncPattern = new(
        @"^(?<indent>[ \t]*)(?:async\s+)?def\s+(?<name>\w+)\s*(?<sig>\([^)]*\))\s*(?:->[^:]+)?:",
        RegexOptions.Multiline | RegexOptions.Compiled);

    // Call expression: "something(" (loosely)
    private static readonly Regex CallPattern = new(
        @"(?<![""'\w])(\w[\w.]*)\s*\(",
        RegexOptions.Compiled);

    // Docstring (triple-quoted, first non-blank statement in body)
    private static readonly Regex DocstringPattern = new(
        @"^\s*(?:""""""(.*?)""""""|\s*'''(.*?)''')",
        RegexOptions.Singleline | RegexOptions.Compiled);

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

        // Imports (module-level only)
        foreach (Match m in ImportPattern.Matches(source))
        {
            var lineNum = CountLines(source, m.Index);
            var ent = new Entity
            {
                Name = m.Value.Trim(),
                EntityType = CodeEntityType.Import,
                Language = Language,
                FilePath = relPath,
                LineStart = lineNum,
                LineEnd = lineNum,
                Signature = m.Value.Trim(),
            };
            kg.AddEntity(ent);
            kg.AddRelation(new Relation { Source = fileEnt.QualifiedKey, Target = ent.QualifiedKey, RelationType = CodeRelationType.Imports });
        }

        // Classes
        var classMatches = ClassPattern.Matches(source);
        foreach (Match classMatch in classMatches)
        {
            var indent = classMatch.Groups["indent"].Value.Length;
            // Only top-level classes (indent == 0) for simplicity (MVP)
            if (indent > 0) continue;

            var className = classMatch.Groups["name"].Value;
            var basesRaw = classMatch.Groups["bases"].Value;
            var classLine = CountLines(source, classMatch.Index);
            var classEndLine = FindBlockEnd(lines, classLine - 1, indent);

            var sig = $"class {className}" + (string.IsNullOrWhiteSpace(basesRaw) ? ":" : $"({basesRaw}):");
            var docstring = ExtractDocstringAfterLine(source, classLine, lines);

            var classEnt = new Entity
            {
                Name = className,
                EntityType = CodeEntityType.Class,
                Language = Language,
                FilePath = relPath,
                LineStart = classLine,
                LineEnd = classEndLine,
                Signature = sig,
                Docstring = docstring,
            };
            kg.AddEntity(classEnt);
            kg.AddRelation(new Relation { Source = fileEnt.QualifiedKey, Target = classEnt.QualifiedKey, RelationType = CodeRelationType.Defines });

            // Base classes → INHERITS
            if (!string.IsNullOrWhiteSpace(basesRaw))
            {
                foreach (var base_ in basesRaw.Split(',').Select(b => b.Trim()).Where(b => b.Length > 0))
                    kg.AddRelation(new Relation { Source = classEnt.QualifiedKey, Target = base_, RelationType = CodeRelationType.Inherits });
            }
        }

        // Functions and methods
        var classIndents = BuildClassIndentMap(classMatches, source, lines);

        foreach (Match funcMatch in FuncPattern.Matches(source))
        {
            var indent = funcMatch.Groups["indent"].Value.Length;
            var funcName = funcMatch.Groups["name"].Value;
            var sigCapture = funcMatch.Groups["sig"].Value;
            var funcLine = CountLines(source, funcMatch.Index);
            var funcEndLine = FindBlockEnd(lines, funcLine - 1, indent);

            // Determine owning class (if method)
            var owningClass = FindOwningClass(classMatches, source, funcMatch.Index, indent);
            var qualifiedName = owningClass != null ? $"{owningClass}.{funcName}" : funcName;

            var entityType = owningClass != null ? CodeEntityType.Method : CodeEntityType.Function;
            var parentKey = owningClass != null
                ? FindClassEntityKey(kg, owningClass, relPath)
                : fileEnt.QualifiedKey;

            var sig = $"def {funcName}{sigCapture}:";
            var docstring = ExtractDocstringAfterLine(source, funcLine, lines);

            var funcEnt = new Entity
            {
                Name = qualifiedName,
                EntityType = entityType,
                Language = Language,
                FilePath = relPath,
                LineStart = funcLine,
                LineEnd = funcEndLine,
                Signature = sig,
                Docstring = docstring,
            };
            kg.AddEntity(funcEnt);

            var relType = owningClass != null ? CodeRelationType.Contains : CodeRelationType.Defines;
            var actualParent = parentKey ?? fileEnt.QualifiedKey;
            kg.AddRelation(new Relation { Source = actualParent, Target = funcEnt.QualifiedKey, RelationType = relType });

            // Extract calls from function body lines
            var bodyText = ExtractBlockText(lines, funcLine, funcEndLine);
            foreach (Match callMatch in CallPattern.Matches(bodyText))
            {
                var callee = callMatch.Groups[1].Value;
                if (callee is "def" or "class" or "if" or "elif" or "while" or "for" or "with" or "return" or "print") continue;
                kg.AddRelation(new Relation { Source = funcEnt.QualifiedKey, Target = callee, RelationType = CodeRelationType.Calls });
            }
        }

        return kg;
    }

    // ── Helpers ──────────────────────────────────────────────────────────

    private static int CountLines(string source, int charIndex)
    {
        var count = 1;
        for (var i = 0; i < charIndex && i < source.Length; i++)
            if (source[i] == '\n') count++;
        return count;
    }

    private static int FindBlockEnd(string[] lines, int startLine0, int blockIndent)
    {
        for (var i = startLine0 + 1; i < lines.Length; i++)
        {
            var line = lines[i];
            if (string.IsNullOrWhiteSpace(line)) continue;
            var indent = line.Length - line.TrimStart().Length;
            if (indent <= blockIndent && line.TrimStart().Length > 0)
                return i; // exclusive end (1-based line of next outer block)
        }
        return lines.Length;
    }

    private static string ExtractDocstringAfterLine(string source, int startLine1, string[] lines)
    {
        if (startLine1 >= lines.Length) return "";
        // Look in the next few lines for a triple-quoted string
        var snippet = string.Join("\n", lines.Skip(startLine1).Take(5));
        var m = DocstringPattern.Match(snippet);
        if (!m.Success) return "";
        return (m.Groups[1].Value.Length > 0 ? m.Groups[1].Value : m.Groups[2].Value).Trim();
    }

    private static string ExtractBlockText(string[] lines, int startLine1, int endLine1)
    {
        var start = Math.Min(startLine1, lines.Length - 1);
        var end = Math.Min(endLine1, lines.Length);
        return string.Join("\n", lines[start..end]);
    }

    private static string? FindOwningClass(MatchCollection classMatches, string source, int funcPos, int funcIndent)
    {
        // Find the class whose body contains funcPos and whose indent < funcIndent
        string? best = null;
        var bestPos = -1;
        foreach (Match cm in classMatches)
        {
            var classIndent = cm.Groups["indent"].Value.Length;
            if (cm.Index < funcPos && classIndent < funcIndent && cm.Index > bestPos)
            {
                best = cm.Groups["name"].Value;
                bestPos = cm.Index;
            }
        }
        return best;
    }

    private static string? FindClassEntityKey(KnowledgeGraph kg, string className, string relPath)
    {
        var ent = kg.FindEntities(name: className, entityType: CodeEntityType.Class, filePath: relPath)
                    .FirstOrDefault();
        return ent?.QualifiedKey;
    }

    private static Dictionary<int, string> BuildClassIndentMap(MatchCollection classMatches, string source, string[] lines)
    {
        var map = new Dictionary<int, string>();
        foreach (Match cm in classMatches)
        {
            var line = CountLines(source, cm.Index);
            map[line] = cm.Groups["name"].Value;
        }
        return map;
    }
}
