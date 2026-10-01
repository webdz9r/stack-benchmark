// ASP.NET Core (minimal APIs) version of the address book API; same routes,
// JSON, SQL and SQLite settings as the Rust reference (backend/rust).
//
//   DOTNET_PROCESSOR_COUNT=4 DB_READERS=4 dotnet run -c Release
//   dotnet run -c Release -- seed 10000

using System.IO.Compression;
using AddressBook;
using Microsoft.AspNetCore.Http.Json;
using Microsoft.AspNetCore.ResponseCompression;
using Microsoft.Extensions.FileProviders;

static string Env(string name, string fallback) => Environment.GetEnvironmentVariable(name) is { Length: > 0 } v ? v : fallback;

var dbPath = Env("DATABASE_PATH", "data/address-book.db");
var migrations = Env("MIGRATIONS_DIR", "../migrations");

if (args is ["sqlite-version"])
{
    // The SQLite this driver links; Docker images record it (CTR-7).
    using var conn = new Microsoft.Data.Sqlite.SqliteConnection("Data Source=:memory:");
    conn.Open();
    using var cmd = conn.CreateCommand();
    cmd.CommandText = "select sqlite_version()";
    Console.WriteLine(cmd.ExecuteScalar());
    return;
}

if (args is ["seed", ..])
{
    Seed.Run(new Db(dbPath, 1, migrations), dbPath, args.Length > 1 ? int.Parse(args[1]) : 10_000);
    return;
}

var readers = int.Parse(Env("DB_READERS", Environment.ProcessorCount.ToString()));
var db = new Db(dbPath, readers, migrations);
using var checkpointer = db.StartCheckpointer();
// Other users see a write within ~1 s; the writer sees it at once (X-Fresh).
var cache = new ResponseCache(db, 64 * 1024 * 1024, TimeSpan.FromSeconds(1));

var builder = WebApplication.CreateSlimBuilder(args);
builder.WebHost.UseUrls($"http://{Env("BIND_ADDR", "127.0.0.1:7884")}");
builder.Logging.SetMinimumLevel(LogLevel.Warning);
builder.Services.Configure<JsonOptions>(o =>
{
    // snake_case both ways, like the other backends (request bodies bind through these options).
    o.SerializerOptions.PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.SnakeCaseLower;
    o.SerializerOptions.TypeInfoResolverChain.Insert(0, AppJson.Default);
});
// gzip at zlib level 6 (CompressionLevel.Optimal), like tower-http on the Rust side.
builder.Services.AddResponseCompression(o => o.Providers.Add<GzipCompressionProvider>());
builder.Services.AddSingleton<IResponseCompressionProvider, MinimumSizeCompressionProvider>();
builder.Services.Configure<GzipCompressionProviderOptions>(o => o.Level = CompressionLevel.Optimal);

var app = builder.Build();
app.UseResponseCompression();

// JSON routes accept a JSON body even without a Content-Type header (spec §7).
// This has to run before routing, which rejects the request otherwise.
app.Use((ctx, next) =>
{
    if (HttpMethods.IsPost(ctx.Request.Method) || HttpMethods.IsPut(ctx.Request.Method))
        ctx.Request.ContentType ??= "application/json";
    return next(ctx);
});

// AppError -> {"error": ...} with its status; malformed JSON -> 400.
app.Use(async (ctx, next) =>
{
    try
    {
        await next(ctx);
    }
    catch (Exception e) when (e is AppError or BadHttpRequestException)
    {
        var (status, message) = e is AppError a ? (a.Status, a.Message) : (400, "invalid JSON");
        var body = System.Text.Json.JsonSerializer.SerializeToUtf8Bytes(new ErrorBody(message), AppJson.Default.ErrorBody);
        ctx.Response.Clear();
        ctx.Response.StatusCode = status;
        ctx.Response.ContentType = "application/json";
        ctx.Response.ContentLength = body.Length;
        await ctx.Response.Body.WriteAsync(body);
    }
});

app.UseRouting();

// Serve the built frontend, like the Rust binary does.
var staticDir = Path.GetFullPath(Env("STATIC_DIR", "../../frontend/dist"));
var hasFrontend = File.Exists(Path.Combine(staticDir, "index.html"));
StaticFileOptions? staticOptions = null;
if (hasFrontend)
{
    staticOptions = new StaticFileOptions { FileProvider = new PhysicalFileProvider(staticDir) };
    app.UseDefaultFiles(new DefaultFilesOptions { FileProvider = staticOptions.FileProvider });
    app.UseStaticFiles(staticOptions);
}

var api = app.MapGroup("/api");

ListQuery Query(HttpRequest r)
{
    long? Int(string name)
    {
        var s = r.Query[name].ToString();
        if (s == "") return null;
        return long.TryParse(s, out var n) ? n : throw new AppError(400, $"{name} must be an integer");
    }
    var favorite = r.Query["favorite"].ToString();
    if (favorite is not ("" or "true" or "false")) throw new AppError(400, "favorite must be true or false");
    return new ListQuery(r.Query["q"].ToString(), Int("tag"), favorite == "true", Int("limit"), Int("offset"));
}

// Cache key for a filtered query; search text is normalized first, so
// "Smith" and "smith " share an entry.
string FilterKey(ListQuery q) => $"{Repo.FtsQuery(q.Q)}|{q.Tag}|{q.Favorite}";

// ---------------------------------------------------------------- reads

api.MapGet("/health", () => "ok");

api.MapGet("/stats", (HttpContext ctx) => cache.Json(ctx, "stats", Repo.GetStats, AppJson.Default.Stats));

api.MapGet("/contacts", async (HttpContext ctx) =>
{
    var q = Query(ctx.Request);
    if (q.Tag is null && !q.Favorite && Repo.FtsQuery(q.Q) is null)
    {
        // Unfiltered pages walk the sort index and are cheap; not worth caching.
        await ctx.Response.WriteAsJsonAsync(await db.Read(c => Repo.ListContacts(c, q)), AppJson.Default.ContactPage);
        return;
    }
    await cache.Json(ctx, $"list|{FilterKey(q)}|{q.Limit}|{q.Offset}", c => Repo.ListContacts(c, q), AppJson.Default.ContactPage);
});

api.MapGet("/contacts/letters", (HttpContext ctx) =>
{
    var q = Query(ctx.Request);
    return cache.Json(ctx, $"letters|{FilterKey(q)}", c => Repo.ListLetters(c, q), AppJson.Default.ListLetterIndex);
});

api.MapGet("/contacts/{id:long}", async (long id) =>
    Results.Json(await db.Read(c => Repo.GetContact(c, id)), AppJson.Default.Contact));

api.MapGet("/tags", (HttpContext ctx) => cache.Json(ctx, "tags", Repo.ListTags, AppJson.Default.ListTagWithCount));

// ---------------------------------------------------------------- writes

api.MapPost("/contacts", async (ContactInput body) =>
{
    var c = Validate.Contact(body);
    var contact = await db.Write(tx => Repo.GetContact(tx, Repo.InsertContact(tx, c)));
    return Results.Json(contact, AppJson.Default.Contact, statusCode: 201);
});

api.MapPut("/contacts/{id:long}", async (long id, ContactInput body) =>
{
    var c = Validate.Contact(body);
    var contact = await db.Write(tx =>
    {
        Repo.UpdateContact(tx, id, c);
        return Repo.GetContact(tx, id);
    });
    return Results.Json(contact, AppJson.Default.Contact);
});

api.MapPut("/contacts/{id:long}/favorite", async (long id, FavoriteBody body) =>
{
    if (body.Favorite is not { } favorite) throw AppError.Validation("favorite must be true or false");
    await db.Write(tx => { Repo.SetFavorite(tx, id, favorite); return 0; });
    return Results.NoContent();
});

api.MapDelete("/contacts/{id:long}", async (long id) =>
{
    await db.Write(tx => { Repo.DeleteContact(tx, id); return 0; });
    return Results.NoContent();
});

api.MapPost("/tags", async (TagInput body) =>
{
    var (name, color) = Validate.Tag(body);
    return Results.Json(await db.Write(tx => Repo.InsertTag(tx, name, color)), AppJson.Default.Tag, statusCode: 201);
});

api.MapPut("/tags/{id:long}", async (long id, TagInput body) =>
{
    var (name, color) = Validate.Tag(body);
    return Results.Json(await db.Write(tx => Repo.UpdateTag(tx, id, name, color)), AppJson.Default.Tag);
});

api.MapDelete("/tags/{id:long}", async (long id) =>
{
    await db.Write(tx => { Repo.DeleteTag(tx, id); return 0; });
    return Results.NoContent();
});

// Unknown /api paths get a JSON 404; anything else falls back to the SPA.
api.MapFallback(() => Results.Json(new ErrorBody("not found"), AppJson.Default.ErrorBody, statusCode: 404));
if (hasFrontend) app.MapFallbackToFile("index.html", staticOptions!);

Console.WriteLine($"database ready: {dbPath} ({readers} readers); listening on http://{Env("BIND_ADDR", "127.0.0.1:7884")}");
app.Run();

/// <summary>gzip only bodies of 32 bytes or more (HTTP-3), when the length is known up front.</summary>
sealed class MinimumSizeCompressionProvider(IServiceProvider services, Microsoft.Extensions.Options.IOptions<ResponseCompressionOptions> options)
    : ResponseCompressionProvider(services, options)
{
    public override bool ShouldCompressResponse(HttpContext context) =>
        context.Response.ContentLength is not < 32 && base.ShouldCompressResponse(context);
}
