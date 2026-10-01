package addressbook;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.util.zip.CRC32;
import java.util.zip.Deflater;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletOutputStream;
import jakarta.servlet.WriteListener;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpServletResponseWrapper;

import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * gzip, level 6, for every response of 32 bytes or more when the client accepts it
 * (HTTP-1..5). Tomcat's own compression isn't used: it skips any response with a
 * strong ETag, which would leave every cached response uncompressed.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class GzipFilter extends OncePerRequestFilter {
    private static final int MIN_SIZE = 32;

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        BufferedResponse buffered = new BufferedResponse(response);
        chain.doFilter(request, buffered);
        buffered.flushWriter();

        byte[] body = buffered.body.toByteArray();
        if (body.length >= MIN_SIZE && acceptsGzip(request) && compressible(response.getContentType())
                && response.getHeader("Content-Encoding") == null) {
            byte[] gz = gzip(body);
            response.setHeader("Content-Encoding", "gzip");
            response.addHeader("Vary", "accept-encoding");
            response.setContentLength(gz.length);
            response.getOutputStream().write(gz);
        } else if (body.length > 0) {
            response.setContentLength(body.length);
            response.getOutputStream().write(body);
        }
    }

    private static boolean acceptsGzip(HttpServletRequest request) {
        String ae = request.getHeader("Accept-Encoding");
        if (ae == null) {
            return false;
        }
        for (String token : ae.split(",")) {
            String[] parts = token.split(";");
            if (!parts[0].trim().equalsIgnoreCase("gzip")) {
                continue;
            }
            for (int i = 1; i < parts.length; i++) {
                String param = parts[i].trim();
                if (param.startsWith("q=")) {
                    try {
                        return Double.parseDouble(param.substring(2)) > 0;
                    } catch (NumberFormatException e) {
                        return false;
                    }
                }
            }
            return true;
        }
        return false;
    }

    /** tower-http's default predicate: everything except images (but SVG), event streams and gRPC. */
    private static boolean compressible(String contentType) {
        if (contentType == null) {
            return true;
        }
        String ct = contentType.toLowerCase();
        if (ct.startsWith("image/")) {
            return ct.startsWith("image/svg+xml");
        }
        return !ct.startsWith("text/event-stream") && !ct.startsWith("application/grpc");
    }

    private static final byte[] GZIP_HEADER = {0x1f, (byte) 0x8b, 8, 0, 0, 0, 0, 0, 0, (byte) 0xff};

    /** One raw deflater per thread, reset between responses, so zlib state isn't allocated per request. */
    private static final ThreadLocal<Deflater> DEFLATER = ThreadLocal.withInitial(() -> new Deflater(6, true));

    static byte[] gzip(byte[] in) {
        Deflater d = DEFLATER.get();
        d.reset();
        d.setInput(in);
        d.finish();
        byte[] out = new byte[GZIP_HEADER.length + in.length / 2 + 64];
        System.arraycopy(GZIP_HEADER, 0, out, 0, GZIP_HEADER.length);
        int n = GZIP_HEADER.length;
        while (!d.finished()) {
            if (n == out.length) {
                out = java.util.Arrays.copyOf(out, out.length * 2);
            }
            n += d.deflate(out, n, out.length - n);
        }
        CRC32 crc = new CRC32();
        crc.update(in);
        if (n + 8 > out.length) {
            out = java.util.Arrays.copyOf(out, n + 8);
        }
        writeIntLE(out, n, (int) crc.getValue());
        writeIntLE(out, n + 4, in.length);
        return java.util.Arrays.copyOf(out, n + 8);
    }

    private static void writeIntLE(byte[] b, int off, int v) {
        b[off] = (byte) v;
        b[off + 1] = (byte) (v >>> 8);
        b[off + 2] = (byte) (v >>> 16);
        b[off + 3] = (byte) (v >>> 24);
    }

    /** Collects the body so its size is known before choosing an encoding. */
    private static final class BufferedResponse extends HttpServletResponseWrapper {
        final ByteArrayOutputStream body = new ByteArrayOutputStream(1024);
        private ServletOutputStream stream;
        private PrintWriter writer;

        BufferedResponse(HttpServletResponse response) {
            super(response);
        }

        @Override
        public ServletOutputStream getOutputStream() {
            if (stream == null) {
                stream = new ServletOutputStream() {
                    @Override
                    public void write(int b) {
                        body.write(b);
                    }

                    @Override
                    public void write(byte[] b, int off, int len) {
                        body.write(b, off, len);
                    }

                    @Override
                    public boolean isReady() {
                        return true;
                    }

                    @Override
                    public void setWriteListener(WriteListener listener) {
                    }
                };
            }
            return stream;
        }

        @Override
        public PrintWriter getWriter() {
            if (writer == null) {
                String enc = getCharacterEncoding();
                Charset cs = enc == null ? StandardCharsets.UTF_8 : Charset.forName(enc);
                writer = new PrintWriter(new OutputStreamWriter(body, cs));
            }
            return writer;
        }

        void flushWriter() {
            if (writer != null) {
                writer.flush();
            }
        }

        @Override
        public void setContentLength(int len) {
        }

        @Override
        public void setContentLengthLong(long len) {
        }

        @Override
        public void setHeader(String name, String value) {
            if (!name.equalsIgnoreCase("Content-Length")) {
                super.setHeader(name, value);
            }
        }

        @Override
        public void addHeader(String name, String value) {
            if (!name.equalsIgnoreCase("Content-Length")) {
                super.addHeader(name, value);
            }
        }

        @Override
        public void flushBuffer() {
        }

        @Override
        public void resetBuffer() {
            body.reset();
        }

        @Override
        public void reset() {
            super.reset();
            body.reset();
        }
    }
}
