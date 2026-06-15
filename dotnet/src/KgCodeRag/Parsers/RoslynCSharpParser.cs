using KgCodeRag.Models;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace KgCodeRag.Parsers;

/// <summary>
/// Roslyn-based C# parser.  Extracts namespaces, classes, structs, interfaces,
/// enums, methods, constructors, and properties — plus INHERITS / IMPLEMENTS /
/// CALLS / CONTAINS / DEFINES / IMPORTS relations.
///
/// Uses <see cref="CSharpSyntaxTree"/> (parse only, no compilation) so no
/// project reference or NuGet restore is required at runtime.
/// </summary>
public sealed class RoslynCSharpParser : ICodeParser
{
    public string Language => "csharp";

    public KnowledgeGraph ParseFile(string filePath, string repoRoot)
    {
        var source = File.ReadAllText(filePath);
        var tree = CSharpSyntaxTree.ParseText(source);
        var root = tree.GetCompilationUnitRoot();
        var relPath = MakeRelative(filePath, repoRoot);

        var kg = new KnowledgeGraph();
        var lines = source.Split('\n');

        // File entity
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

        // Using directives live directly on CompilationUnitSyntax, not in Members
        foreach (var u in root.Usings)
            HandleUsing(u, relPath, kg, fileEnt.QualifiedKey);

        WalkMembers(root.Members, source, relPath, kg, parentKey: fileEnt.QualifiedKey, className: "");

        return kg;
    }

    // ── Walker ─────────────────────────────────────────────────────────

    private void WalkMembers(
        SyntaxList<MemberDeclarationSyntax> members,
        string source,
        string relPath,
        KnowledgeGraph kg,
        string parentKey,
        string className)
    {
        foreach (var member in members)
        {
            switch (member)
            {
                case NamespaceDeclarationSyntax ns:
                    HandleNamespace(ns, source, relPath, kg, parentKey);
                    break;
                case FileScopedNamespaceDeclarationSyntax fsns:
                    HandleFileScopedNamespace(fsns, source, relPath, kg, parentKey);
                    break;
                case ClassDeclarationSyntax cls:
                    HandleTypeDecl(cls, source, relPath, kg, parentKey, CodeEntityType.Class);
                    break;
                case StructDeclarationSyntax str:
                    HandleTypeDecl(str, source, relPath, kg, parentKey, CodeEntityType.Struct);
                    break;
                case InterfaceDeclarationSyntax iface:
                    HandleTypeDecl(iface, source, relPath, kg, parentKey, CodeEntityType.Interface);
                    break;
                case EnumDeclarationSyntax enm:
                    HandleEnum(enm, relPath, kg, parentKey);
                    break;
                case MethodDeclarationSyntax mth:
                    HandleMethod(mth, source, relPath, kg, parentKey, className);
                    break;
                case ConstructorDeclarationSyntax ctor:
                    HandleConstructor(ctor, source, relPath, kg, parentKey, className);
                    break;
                case PropertyDeclarationSyntax prop:
                    HandleProperty(prop, relPath, kg, parentKey, className);
                    break;
            }
        }
    }

    // ── Using directives ────────────────────────────────────────────────

    private void HandleUsing(
        UsingDirectiveSyntax node,
        string relPath,
        KnowledgeGraph kg,
        string parentKey)
    {
        var text = node.ToString().Trim();
        var ent = new Entity
        {
            Name = text,
            EntityType = CodeEntityType.Import,
            Language = Language,
            FilePath = relPath,
            LineStart = GetLine(node),
            LineEnd = GetEndLine(node),
            Signature = text,
        };
        kg.AddEntity(ent);
        kg.AddRelation(new Relation { Source = parentKey, Target = ent.QualifiedKey, RelationType = CodeRelationType.Imports });
    }

    // ── Namespaces ───────────────────────────────────────────────────────

    private void HandleNamespace(
        NamespaceDeclarationSyntax node,
        string source,
        string relPath,
        KnowledgeGraph kg,
        string parentKey)
    {
        var name = node.Name.ToString();
        var ent = MakeEntity(name, CodeEntityType.Namespace, relPath, node);
        kg.AddEntity(ent);
        kg.AddRelation(new Relation { Source = parentKey, Target = ent.QualifiedKey, RelationType = CodeRelationType.Defines });

        // Walk children using the SyntaxList from the namespace body
        WalkMembers(node.Members, source, relPath, kg, parentKey: ent.QualifiedKey, className: "");
    }

    private void HandleFileScopedNamespace(
        FileScopedNamespaceDeclarationSyntax node,
        string source,
        string relPath,
        KnowledgeGraph kg,
        string parentKey)
    {
        var name = node.Name.ToString();
        var ent = MakeEntity(name, CodeEntityType.Namespace, relPath, node);
        kg.AddEntity(ent);
        kg.AddRelation(new Relation { Source = parentKey, Target = ent.QualifiedKey, RelationType = CodeRelationType.Defines });
        // Using directives can appear inside file-scoped namespaces
        foreach (var u in node.Usings) HandleUsing(u, relPath, kg, ent.QualifiedKey);
        WalkMembers(node.Members, source, relPath, kg, parentKey: ent.QualifiedKey, className: "");
    }

    // ── Types (class / struct / interface) ───────────────────────────────

    private void HandleTypeDecl(
        TypeDeclarationSyntax node,
        string source,
        string relPath,
        KnowledgeGraph kg,
        string parentKey,
        CodeEntityType entityType)
    {
        var name = node.Identifier.Text;
        var sig = FirstLine(node.ToString());
        var doc = ExtractXmlDoc(node);
        var ent = new Entity
        {
            Name = name,
            EntityType = entityType,
            Language = Language,
            FilePath = relPath,
            LineStart = GetLine(node),
            LineEnd = GetEndLine(node),
            Signature = sig,
            Docstring = doc,
        };
        kg.AddEntity(ent);
        kg.AddRelation(new Relation { Source = parentKey, Target = ent.QualifiedKey, RelationType = CodeRelationType.Defines });

        // Base types → INHERITS / IMPLEMENTS
        if (node.BaseList is not null)
        {
            foreach (var baseType in node.BaseList.Types)
            {
                var baseName = baseType.Type.ToString();
                var relType = entityType == CodeEntityType.Interface
                    ? CodeRelationType.Inherits
                    : baseName.StartsWith('I') && baseName.Length > 1 && char.IsUpper(baseName[1])
                        ? CodeRelationType.Implements
                        : CodeRelationType.Inherits;
                kg.AddRelation(new Relation { Source = ent.QualifiedKey, Target = baseName, RelationType = relType });
            }
        }

        WalkMembers(node.Members, source, relPath, kg, parentKey: ent.QualifiedKey, className: name);
    }

    // ── Enums ────────────────────────────────────────────────────────────

    private void HandleEnum(
        EnumDeclarationSyntax node,
        string relPath,
        KnowledgeGraph kg,
        string parentKey)
    {
        var ent = MakeEntity(node.Identifier.Text, CodeEntityType.Enum, relPath, node);
        kg.AddEntity(ent);
        kg.AddRelation(new Relation { Source = parentKey, Target = ent.QualifiedKey, RelationType = CodeRelationType.Defines });
    }

    // ── Methods ──────────────────────────────────────────────────────────

    private void HandleMethod(
        MethodDeclarationSyntax node,
        string source,
        string relPath,
        KnowledgeGraph kg,
        string parentKey,
        string className)
    {
        var name = string.IsNullOrEmpty(className)
            ? node.Identifier.Text
            : $"{className}.{node.Identifier.Text}";

        var sig = FirstLine(node.ToString());
        var doc = ExtractXmlDoc(node);
        var ent = new Entity
        {
            Name = name,
            EntityType = CodeEntityType.Method,
            Language = Language,
            FilePath = relPath,
            LineStart = GetLine(node),
            LineEnd = GetEndLine(node),
            Signature = sig,
            Docstring = doc,
        };
        kg.AddEntity(ent);
        kg.AddRelation(new Relation { Source = parentKey, Target = ent.QualifiedKey, RelationType = CodeRelationType.Contains });

        // Extract CALLS from body
        if (node.Body is not null)
            ExtractCalls(node.Body, ent.QualifiedKey, kg);
        else if (node.ExpressionBody is not null)
            ExtractCallsFromExpression(node.ExpressionBody.Expression, ent.QualifiedKey, kg);
    }

    private void HandleConstructor(
        ConstructorDeclarationSyntax node,
        string source,
        string relPath,
        KnowledgeGraph kg,
        string parentKey,
        string className)
    {
        var name = string.IsNullOrEmpty(className)
            ? node.Identifier.Text
            : $"{className}.{node.Identifier.Text}";

        var sig = FirstLine(node.ToString());
        var ent = new Entity
        {
            Name = name,
            EntityType = CodeEntityType.Method,
            Language = Language,
            FilePath = relPath,
            LineStart = GetLine(node),
            LineEnd = GetEndLine(node),
            Signature = sig,
        };
        kg.AddEntity(ent);
        kg.AddRelation(new Relation { Source = parentKey, Target = ent.QualifiedKey, RelationType = CodeRelationType.Contains });

        if (node.Body is not null)
            ExtractCalls(node.Body, ent.QualifiedKey, kg);
    }

    // ── Properties ───────────────────────────────────────────────────────

    private void HandleProperty(
        PropertyDeclarationSyntax node,
        string relPath,
        KnowledgeGraph kg,
        string parentKey,
        string className)
    {
        var name = string.IsNullOrEmpty(className)
            ? node.Identifier.Text
            : $"{className}.{node.Identifier.Text}";

        var ent = new Entity
        {
            Name = name,
            EntityType = CodeEntityType.Property,
            Language = Language,
            FilePath = relPath,
            LineStart = GetLine(node),
            LineEnd = GetEndLine(node),
            Signature = $"{node.Type} {name}",
        };
        kg.AddEntity(ent);
        kg.AddRelation(new Relation { Source = parentKey, Target = ent.QualifiedKey, RelationType = CodeRelationType.Contains });
    }

    // ── Call extraction ──────────────────────────────────────────────────

    private static void ExtractCalls(SyntaxNode body, string callerKey, KnowledgeGraph kg)
    {
        foreach (var invocation in body.DescendantNodes().OfType<InvocationExpressionSyntax>())
            RecordCall(invocation.Expression.ToString(), callerKey, kg);
    }

    private static void ExtractCallsFromExpression(ExpressionSyntax expr, string callerKey, KnowledgeGraph kg)
    {
        foreach (var invocation in expr.DescendantNodesAndSelf().OfType<InvocationExpressionSyntax>())
            RecordCall(invocation.Expression.ToString(), callerKey, kg);
    }

    private static void RecordCall(string callee, string callerKey, KnowledgeGraph kg) =>
        kg.AddRelation(new Relation { Source = callerKey, Target = callee, RelationType = CodeRelationType.Calls });

    // ── Utilities ────────────────────────────────────────────────────────

    private Entity MakeEntity(string name, CodeEntityType type, string relPath, SyntaxNode node) =>
        new()
        {
            Name = name,
            EntityType = type,
            Language = Language,
            FilePath = relPath,
            LineStart = GetLine(node),
            LineEnd = GetEndLine(node),
        };

    private static string ExtractXmlDoc(SyntaxNode node)
    {
        var trivia = node.GetLeadingTrivia()
            .Where(t => t.IsKind(SyntaxKind.SingleLineDocumentationCommentTrivia) ||
                        t.IsKind(SyntaxKind.MultiLineDocumentationCommentTrivia))
            .ToList();
        if (trivia.Count == 0) return "";
        // Collect <summary> text
        var xmlText = string.Concat(trivia.Select(t => t.ToString()));
        var summaryMatch = System.Text.RegularExpressions.Regex.Match(
            xmlText, @"<summary>(.*?)</summary>",
            System.Text.RegularExpressions.RegexOptions.Singleline);
        if (summaryMatch.Success)
            return summaryMatch.Groups[1].Value.Trim(' ', '\n', '\r', '/', '*');
        return xmlText.Trim(' ', '\n', '\r', '/', '*');
    }

    private static string FirstLine(string text)
    {
        var idx = text.IndexOfAny(['\n', '\r']);
        return idx >= 0 ? text[..idx].Trim() : text.Trim();
    }

    private static int GetLine(SyntaxNode node) =>
        node.GetLocation().GetLineSpan().StartLinePosition.Line + 1;

    private static int GetEndLine(SyntaxNode node) =>
        node.GetLocation().GetLineSpan().EndLinePosition.Line + 1;

    private static string MakeRelative(string filePath, string repoRoot)
    {
        var rel = Path.GetRelativePath(repoRoot, filePath);
        return rel.Replace('\\', '/');
    }
}
