package addressbook;

import java.io.IOException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import jakarta.servlet.http.HttpServletRequest;

import addressbook.Models.ApiException;

import org.springframework.http.MediaType;
import org.springframework.http.MediaTypeFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

/** The built Vue app (ARCH-17): files from STATIC_DIR, index.html for any other path. */
@Controller
public class StaticController {
    private final Path root;
    private final Path index;

    public StaticController(Config config) throws IOException {
        Path dir = config.staticDir().toAbsolutePath().normalize();
        this.root = Files.isDirectory(dir) ? dir.toRealPath() : dir;
        this.index = root.resolve("index.html");
    }

    @GetMapping("/**")
    public ResponseEntity<byte[]> serve(HttpServletRequest request) throws IOException {
        if (!Files.isRegularFile(index)) {
            throw ApiException.notFound(); // no frontend build (ARCH-19)
        }
        String path = URLDecoder.decode(request.getRequestURI(), StandardCharsets.UTF_8);
        Path file = root.resolve(path.replaceFirst("^/+", "")).normalize();
        if (!file.startsWith(root) || !Files.isRegularFile(file)) {
            file = index;
        }
        MediaType type = MediaTypeFactory.getMediaType(file.getFileName().toString())
            .orElse(MediaType.APPLICATION_OCTET_STREAM);
        return ResponseEntity.ok().contentType(type).body(Files.readAllBytes(file));
    }
}
