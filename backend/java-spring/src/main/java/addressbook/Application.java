package addressbook;

import java.nio.file.Files;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.web.server.context.WebServerInitializedEvent;
import org.springframework.context.annotation.Bean;
import org.springframework.context.event.EventListener;

/** Entry point: the server, or the seeder with `seed [COUNT]` (ARCH-4). */
@SpringBootApplication
public class Application {
    private static final Logger log = LoggerFactory.getLogger(Application.class);

    public static void main(String[] args) throws Exception {
        if (args.length > 0 && args[0].equals("sqlite-version")) {
            // The SQLite this driver links; Docker images record it (CTR-7).
            try (var conn = java.sql.DriverManager.getConnection("jdbc:sqlite::memory:");
                 var rs = conn.createStatement().executeQuery("select sqlite_version()")) {
                rs.next();
                System.out.println(rs.getString(1));
            }
            return;
        }
        Config config = Config.fromEnv();
        if (args.length > 0 && args[0].equals("seed")) {
            Seeder.run(config, args);
            return;
        }
        SpringApplication app = new SpringApplication(Application.class);
        app.setDefaultProperties(Map.of(
            "server.address", config.host(),
            "server.port", String.valueOf(config.port())));
        app.run(args);
    }

    @Bean
    Config config() {
        return Config.fromEnv();
    }

    /** Opened before Tomcat starts listening, so /api/health works as soon as it answers (ARCH-15). */
    @Bean(destroyMethod = "close")
    Db db(Config config) throws Exception {
        log.info("database {} with {} readers", config.databasePath().toAbsolutePath(), config.readers());
        return Db.open(config.databasePath(), config.migrationsDir(), config.readers(), true);
    }

    @Bean
    ResponseCache responseCache() {
        return new ResponseCache(64L * 1024 * 1024, 30_000);
    }

    @EventListener
    void started(WebServerInitializedEvent event) {
        Config config = config();
        log.info("listening on http://{}:{}", config.host(), event.getWebServer().getPort());
        if (Files.isRegularFile(config.staticDir().resolve("index.html"))) {
            log.info("serving frontend from {}", config.staticDir().toAbsolutePath().normalize());
        } else {
            log.info("no frontend build at {}; API only", config.staticDir().toAbsolutePath().normalize());
        }
    }
}
