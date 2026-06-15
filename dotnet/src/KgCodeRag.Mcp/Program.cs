using KgCodeRag.Mcp;
using KgCodeRag.Mcp.Tools;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

// ── Parse transport args before host is built ──────────────────────────────
var transport = "stdio";
var host = "127.0.0.1";
var port = 8000;

for (var i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--transport" when i + 1 < args.Length: transport = args[++i]; break;
        case "--host" when i + 1 < args.Length: host = args[++i]; break;
        case "--port" when i + 1 < args.Length:
            port = int.TryParse(args[++i], out var p) ? p : 8000;
            break;
    }
}

// ── Build host ─────────────────────────────────────────────────────────────
// Always use WebApplication.CreateBuilder so ASP.NET Core is available for HTTP transports.
var builder = WebApplication.CreateBuilder(args);

builder.Logging.ClearProviders();
// For stdio, only warn to stderr so stdout stays clean for JSON-RPC
var logLevel = transport == "stdio" ? LogLevel.Warning : LogLevel.Information;
builder.Logging.AddConsole(opts => opts.LogToStandardErrorThreshold = logLevel);

// ── Register core services ─────────────────────────────────────────────────
builder.Services.AddSingleton<ServerState>();
builder.Services.AddSingleton<GitHistoryTools>();
builder.Services.AddSingleton<WorkItemTools>();
builder.Services.AddSingleton<BlameContextTools>();

// ── Register MCP server ────────────────────────────────────────────────────
var mcp = builder.Services.AddMcpServer()
    .WithTools<CodeSearchTools>()
    .WithTools<CodeStructureTools>()
    .WithTools<GraphStatsTools>()
    .WithTools<ProjectManagementTools>()
    .WithTools<GitHistoryTools>()
    .WithTools<WorkItemTools>()
    .WithTools<BlameContextTools>();

// ── Select transport ───────────────────────────────────────────────────────
switch (transport.ToLowerInvariant())
{
    case "stdio":
        mcp.WithStdioServerTransport();
        break;
    case "sse":
    case "streamable-http":
        mcp.WithHttpTransport();
        builder.WebHost.UseUrls($"http://{host}:{port}");
        break;
    default:
        Console.Error.WriteLine($"Unknown transport '{transport}'. Using stdio.");
        mcp.WithStdioServerTransport();
        break;
}

var app = builder.Build();

// ── Initialise server state eagerly before accepting MCP requests ─────────
Console.Error.WriteLine("[kg-mcp] Starting server, loading graph...");
var serverState = app.Services.GetRequiredService<ServerState>();
serverState.LoadGraph();
Console.Error.WriteLine("[kg-mcp] Server ready.");

if (transport is "sse" or "streamable-http")
{
    app.MapMcp();
    await app.RunAsync();
}
else
{
    await app.RunAsync();
}
