using System.CommandLine;
using System.CommandLine.Invocation;
using KgCodeRag.Config;
using KgCodeRag.Indexing;
using KgCodeRag.Models;
using Microsoft.Extensions.Logging;

// ── Root command ───────────────────────────────────────────────────────────
var root = new RootCommand("KG Code RAG — index source code and expose it via MCP tools");

// ── kg-index subcommand ────────────────────────────────────────────────────
var indexCmd = new Command("index", "Index a repo (or project scope) and write the graph cache");

var repoOpt = new Option<string?>("--repo", "Repo root path");
var projectOpt = new Option<string?>("--project", "Project name (from projects.json or env)");
var scopeOpt = new Option<string?>("--scope", "Comma-separated scope paths relative to repo root");
var cacheOpt = new Option<string?>("--cache-dir", "Override cache directory");
var gitOpt = new Option<bool>("--git", "Include git history layer");
var adoOpt = new Option<bool>("--ado", "Hydrate Azure DevOps work items");

indexCmd.AddOption(repoOpt);
indexCmd.AddOption(projectOpt);
indexCmd.AddOption(scopeOpt);
indexCmd.AddOption(cacheOpt);
indexCmd.AddOption(gitOpt);
indexCmd.AddOption(adoOpt);

indexCmd.SetHandler(async (repo, project, scope, cacheDir, withGit, withAdo) =>
{
    // Apply env overrides before loading config
    if (!string.IsNullOrWhiteSpace(repo)) Environment.SetEnvironmentVariable("KG_REPO_ROOT", repo);
    if (!string.IsNullOrWhiteSpace(project)) Environment.SetEnvironmentVariable("KG_PROJECT_NAME", project);
    if (!string.IsNullOrWhiteSpace(scope)) Environment.SetEnvironmentVariable("KG_SCOPE_PATHS", scope);
    if (!string.IsNullOrWhiteSpace(cacheDir)) Environment.SetEnvironmentVariable("KG_CACHE_DIR", cacheDir);

    var settings = AppSettings.Default;
    var cfg = ProjectsConfig.Load();
    var activeProject = cfg.DefaultProjectName(project);

    Console.WriteLine($"[kg-index] Project:   {activeProject}");
    Console.WriteLine($"[kg-index] Repo root: {cfg.GetRepoRoot()}");

    List<string>? scopePaths = null;
    if (cfg.Projects.ContainsKey(activeProject))
        scopePaths = cfg.ResolveAbsolutePaths(activeProject);

    Console.WriteLine($"[kg-index] Scope:     {(scopePaths is { Count: > 0 } ? string.Join(", ", scopePaths) : "(entire repo)")}");

    // Build a console logger so parse warnings are visible
    using var logFactory = LoggerFactory.Create(b =>
        b.AddSimpleConsole(o => { o.SingleLine = true; o.TimestampFormat = null; })
         .SetMinimumLevel(LogLevel.Warning));

    var indexer = new KgIndexer(logFactory.CreateLogger<KgIndexer>());

    // ── Discover files first so we can report counts ──────────────────
    var discoveredFiles = indexer.DiscoverFiles(cfg.GetRepoRoot(), scopePaths: scopePaths);
    Console.WriteLine($"[kg-index] Files discovered: {discoveredFiles.Count}");

    if (discoveredFiles.Count == 0)
    {
        Console.WriteLine($"[kg-index] WARNING: No parseable files found.");
        Console.WriteLine($"[kg-index]   Extensions searched: {string.Join(" ", AppSettings.DefaultIndexExtensions)}");
        Console.WriteLine($"[kg-index]   Skipped dir names:   {string.Join(" ", AppSettings.DefaultSkipDirs)}");
        // Still save an empty graph so the project is registered
    }

    var progress = new ConsoleProgress();

    Console.WriteLine("[kg-index] Indexing source files...");
    var kg = indexer.IndexRepo(cfg.GetRepoRoot(), scopePaths: scopePaths, progress: progress);
    Console.WriteLine();
    Console.WriteLine($"[kg-index] Indexed {kg.Entities.Count:N0} entities, {kg.Relations.Count:N0} relations");

    var metadata = new GraphMetadata
    {
        ProjectName = activeProject,
        RepoRoot = cfg.GetRepoRoot(),
        ScopePaths = scopePaths?.Select(p => Path.GetRelativePath(cfg.GetRepoRoot(), p)).ToList() ?? ["."],
        IndexedAt = DateTime.UtcNow.ToString("O"),
    };

    if (withGit)
    {
        Console.WriteLine("[kg-index] Git history layer: not yet implemented (Phase 4)");
        // TODO Phase 4: GitHistoryBuilder.Build(kg, metadata, cfg.GetRepoRoot(), scopePaths)
    }

    if (withAdo)
    {
        Console.WriteLine("[kg-index] ADO work items: not yet implemented (Phase 5)");
        // TODO Phase 5: AdoClient.Hydrate(kg, metadata)
    }

    var cachePath = cfg.GraphCachePath(activeProject);
    var registry = new ProjectRegistry(settings.DataDir);
    indexer.SaveGraph(kg, metadata, cachePath, registry);
    Console.WriteLine($"[kg-index] Graph saved to: {cachePath}");

}, repoOpt, projectOpt, scopeOpt, cacheOpt, gitOpt, adoOpt);

root.AddCommand(indexCmd);

// ── Entry point ────────────────────────────────────────────────────────────
await root.InvokeAsync(args);

// ── Helper ────────────────────────────────────────────────────────────────
sealed class ConsoleProgress : IProgress<(int done, int total, string file)>
{
    public void Report((int done, int total, string file) v) =>
        Console.Write($"\r  [{v.done}/{v.total}] {Path.GetFileName(v.file)}   ");
}
