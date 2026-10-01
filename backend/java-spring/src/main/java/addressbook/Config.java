package addressbook;

import java.nio.file.Path;

/** Environment configuration (01-architecture.md §2). */
public record Config(Path databasePath, Path migrationsDir, Path staticDir, int readers, String host, int port) {
    static final int DEFAULT_PORT = 7886;

    public static Config fromEnv() {
        String bind = env("BIND_ADDR", null);
        String host = "127.0.0.1";
        int port = DEFAULT_PORT;
        if (bind != null) {
            int colon = bind.lastIndexOf(':');
            host = bind.substring(0, colon);
            port = Integer.parseInt(bind.substring(colon + 1));
        } else if (System.getenv("PORT") != null) {
            port = Integer.parseInt(System.getenv("PORT"));
        }
        int readers = Integer.parseInt(env("DB_READERS", String.valueOf(Runtime.getRuntime().availableProcessors())));
        return new Config(
            Path.of(env("DATABASE_PATH", "data/address-book.db")),
            Path.of(env("MIGRATIONS_DIR", "../migrations")),
            Path.of(env("STATIC_DIR", "../../frontend/dist")),
            Math.max(1, readers), host, port);
    }

    private static String env(String name, String dflt) {
        String v = System.getenv(name);
        return v == null || v.isEmpty() ? dflt : v;
    }
}
