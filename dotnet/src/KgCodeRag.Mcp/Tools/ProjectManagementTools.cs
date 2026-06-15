using System.ComponentModel;
using System.Text;
using System.Text.Json;
using KgCodeRag.Config;
using ModelContextProtocol.Server;

namespace KgCodeRag.Mcp.Tools;

[McpServerToolType]
public sealed class ProjectManagementTools(ServerState state)
{
    // ── list_projects ─────────────────────────────────────────────────────

    [McpServerTool]
    [Description("List all configured projects and their indexed status from the project registry.")]
    public string ListProjects()
    {
        var sb = new StringBuilder();
        sb.AppendLine("## Configured Projects");
        sb.AppendLine();

        foreach (var (name, scope) in state.ProjectsConfig.Projects)
        {
            var active = name == state.ActiveProject ? " ← active" : "";
            sb.AppendLine($"**{name}**{active}");
            if (!string.IsNullOrEmpty(scope.Description)) sb.AppendLine($"  {scope.Description}");
            sb.AppendLine($"  Paths: {string.Join(", ", scope.Paths)}");
        }

        sb.AppendLine();
        sb.AppendLine("## Indexed Projects (registry)");
        sb.AppendLine();

        var entries = state.Registry.ListExisting();
        if (entries.Count == 0)
        {
            sb.AppendLine("No indexed projects found in registry.");
        }
        else
        {
            foreach (var e in entries)
            {
                sb.AppendLine($"**{e.ProjectName}** — indexed: {e.IndexedAt}");
                sb.AppendLine($"  entities: {e.EntityCount:N0}  relations: {e.RelationCount:N0}");
                sb.AppendLine($"  git: {(e.HasGitHistory ? "yes" : "no")}  work items: {(e.HasWorkItems ? "yes" : "no")}");
                sb.AppendLine($"  cache: {e.GraphPath}");
            }
        }

        return sb.ToString();
    }

    // ── switch_project ────────────────────────────────────────────────────

    [McpServerTool]
    [Description("Switch the active project scope. The new graph is loaded from cache or indexed from source.")]
    public string SwitchProject(
        [Description("Exact project name as configured (use list_projects to see available names).")] string projectName)
    {
        state.SwitchProject(projectName);
        var kg = state.GetKg();
        return $"Switched to project '{projectName}'. Graph has {kg.Entities.Count:N0} entities and {kg.Relations.Count:N0} relations.";
    }

    // ── index_project ─────────────────────────────────────────────────────

    [McpServerTool]
    [Description("Index (or re-index) a specific project by name and load it as the active project.")]
    public string IndexProject(
        [Description("Project name to index.")] string projectName)
    {
        if (!state.ProjectsConfig.Projects.ContainsKey(projectName))
            return $"Unknown project '{projectName}'. Use list_projects to see configured projects.";

        state.SwitchProject(projectName);
        state.ReindexRepo();
        var kg = state.GetKg();
        return $"Project '{projectName}' indexed. Graph has {kg.Entities.Count:N0} entities and {kg.Relations.Count:N0} relations.";
    }

    // ── get_project_metadata ──────────────────────────────────────────────

    [McpServerTool]
    [Description("Return detailed metadata about the currently active project.")]
    public string GetProjectMetadata()
    {
        var meta = state.Metadata;
        if (meta is null) return "No metadata available. Load a project first.";

        var sb = new StringBuilder();
        sb.AppendLine($"**Project**: {meta.ProjectName}");
        sb.AppendLine($"**Repo root**: {meta.RepoRoot}");
        sb.AppendLine($"**Scope paths**: {string.Join(", ", meta.ScopePaths)}");
        sb.AppendLine($"**Indexed at**: {meta.IndexedAt}");
        sb.AppendLine($"**Entity count**: {meta.EntityCount:N0}");
        sb.AppendLine($"**Relation count**: {meta.RelationCount:N0}");
        sb.AppendLine($"**Git history**: {(meta.HasGitHistory ? $"yes (since: {meta.GitSince})" : "no")}");
        sb.AppendLine($"**Work items**: {(meta.HasWorkItems ? "yes" : "no")}");
        sb.AppendLine($"**Extensions**: {string.Join(", ", meta.Extensions)}");
        return sb.ToString();
    }

    // ── get_indexed_project_info ──────────────────────────────────────────

    [McpServerTool]
    [Description("Look up any indexed project by name (partial match) from the project registry.")]
    public string GetIndexedProjectInfo(
        [Description("Project name or partial name to look up.")] string projectName)
    {
        var entries = state.Registry.ListExisting();
        var matches = entries
            .Where(e => e.ProjectName.Contains(projectName, StringComparison.OrdinalIgnoreCase))
            .ToList();

        if (matches.Count == 0) return $"No indexed project found matching '{projectName}'.";

        var sb = new StringBuilder();
        foreach (var e in matches)
        {
            sb.AppendLine($"**{e.ProjectName}**");
            sb.AppendLine($"  Repo root:    {e.RepoRoot}");
            sb.AppendLine($"  Scope paths:  {string.Join(", ", e.ScopePaths)}");
            sb.AppendLine($"  Indexed at:   {e.IndexedAt}");
            sb.AppendLine($"  Entities:     {e.EntityCount:N0}");
            sb.AppendLine($"  Relations:    {e.RelationCount:N0}");
            sb.AppendLine($"  Git history:  {(e.HasGitHistory ? "yes" : "no")}");
            sb.AppendLine($"  Work items:   {(e.HasWorkItems ? "yes" : "no")}");
            sb.AppendLine($"  Cache file:   {e.GraphPath}");
            sb.AppendLine();
        }

        return sb.ToString();
    }
}
