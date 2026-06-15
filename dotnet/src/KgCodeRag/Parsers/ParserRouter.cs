namespace KgCodeRag.Parsers;

/// <summary>
/// Routes source files to the appropriate <see cref="ICodeParser"/> by extension.
/// Returns <see langword="null"/> for unsupported languages.
///
/// Supported parsers: C# (Roslyn), Python (regex), C/C++ (regex), Fortran (regex).
/// Add more parsers by extending <see cref="BuildMap"/>.
/// </summary>
public sealed class ParserRouter
{
    private readonly Dictionary<string, ICodeParser> _map;

    public ParserRouter() => _map = BuildMap();

    /// <summary>Returns the parser for this file extension, or <see langword="null"/>.</summary>
    public ICodeParser? GetParser(string fileExtension)
    {
        var ext = fileExtension.ToLowerInvariant();
        return _map.GetValueOrDefault(ext);
    }

    /// <summary>Returns the language identifier for an extension, or <see langword="null"/>.</summary>
    public static string? LanguageForExtension(string fileExtension) =>
        fileExtension.ToLowerInvariant() switch
        {
            ".cs" => "csharp",
            ".py" => "python",
            ".cpp" or ".cc" or ".cxx" or ".c" => "cpp",
            ".h" or ".hpp" or ".hxx" => "cpp",
            ".ts" or ".tsx" => "typescript",
            ".js" or ".jsx" => "javascript",
            ".kt" or ".kts" => "kotlin",
            ".ps1" or ".psm1" or ".psd1" => "powershell",
            ".f" or ".f90" or ".f95" or ".f03" or ".f08" or ".for" or ".fpp" => "fortran",
            ".pas" or ".pp" or ".dpr" or ".lpr" or ".iss" => "pascal",
            ".build" => "nant",
            _ => null,
        };

    private static Dictionary<string, ICodeParser> BuildMap()
    {
        var csharp = new RoslynCSharpParser();
        var python = new RegexPythonParser();
        var cpp = new RegexCppParser();
        var fortran = new RegexFortranParser();

        return new(StringComparer.OrdinalIgnoreCase)
        {
            [".cs"] = csharp,
            [".py"] = python,
            [".cpp"] = cpp,
            [".cc"]  = cpp,
            [".cxx"] = cpp,
            [".c"]   = cpp,
            [".h"]   = cpp,
            [".hpp"] = cpp,
            [".hxx"] = cpp,
            [".f"]   = fortran,
            [".f90"] = fortran,
            [".f95"] = fortran,
            [".f03"] = fortran,
            [".f08"] = fortran,
            [".for"] = fortran,
            [".fpp"] = fortran,
        };
    }
}
