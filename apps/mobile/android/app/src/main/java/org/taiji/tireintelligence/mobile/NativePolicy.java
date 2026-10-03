package org.taiji.tireintelligence.mobile;

import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

/** All untrusted values are checked before network or OS APIs are called. */
public final class NativePolicy {
    public static final int MAX_REQUEST_BYTES = 10 * 1024 * 1024;
    public static final int MAX_RESPONSE_BYTES = 32 * 1024 * 1024;
    private NativePolicy() {}
    public interface MetadataValidator { boolean valid(byte[] bytes); }
    public static final class Request {
        public final String id, path, method;
        public final Map<String, String> headers;
        public final byte[] body;
        Request(String id, String path, String method, Map<String, String> headers, byte[] body) {
            this.id = id; this.path = path; this.method = method; this.headers = headers; this.body = body;
        }
    }
    public static void requestId(String value) throws NativeFailure {
        if (value == null || !value.matches("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")) throw new NativeFailure("INVALID_REQUEST_ID");
        try { UUID.fromString(value); } catch (IllegalArgumentException ignored) { throw new NativeFailure("INVALID_REQUEST_ID"); }
    }
    static boolean control(String value) { return value.codePoints().anyMatch(Character::isISOControl); }
    public static String utf8(byte[] bytes, String code) throws NativeFailure {
        try { return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString(); }
        catch (CharacterCodingException ignored) { throw new NativeFailure(code); }
    }
    private static String decoded(String value) throws NativeFailure {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        for (int i = 0; i < value.length();) {
            if (value.charAt(i) == '%') {
                if (i + 2 >= value.length()) throw new NativeFailure("INVALID_API_PATH");
                int high = Character.digit(value.charAt(i + 1), 16), low = Character.digit(value.charAt(i + 2), 16);
                if (high < 0 || low < 0) throw new NativeFailure("INVALID_API_PATH");
                bytes.write((high << 4) | low); i += 3;
            } else {
                int cp = value.codePointAt(i);
                byte[] encoded = new String(Character.toChars(cp)).getBytes(StandardCharsets.UTF_8);
                bytes.write(encoded, 0, encoded.length); i += Character.charCount(cp);
            }
        }
        return utf8(bytes.toByteArray(), "INVALID_API_PATH");
    }
    public static void path(String value) throws NativeFailure {
        if (value == null || value.getBytes(StandardCharsets.UTF_8).length > 4096 || value.indexOf('\\') >= 0 || value.indexOf('#') >= 0 || control(value)) throw new NativeFailure("INVALID_API_PATH");
        int split = value.indexOf('?');
        String route = split < 0 ? value : value.substring(0, split), query = split < 0 ? "" : value.substring(split + 1);
        if (!(route.equals("/health") || route.startsWith("/v1/")) || route.contains("//")) throw new NativeFailure("INVALID_API_PATH");
        String parsed = decoded(route);
        if (parsed.indexOf('\\') >= 0 || parsed.indexOf('%') >= 0 || parsed.indexOf('#') >= 0 || parsed.indexOf('?') >= 0 || control(parsed)
                || parsed.chars().filter(c -> c == '/').count() != route.chars().filter(c -> c == '/').count()) throw new NativeFailure("INVALID_API_PATH");
        for (String part : parsed.split("/")) if (part.equals(".") || part.equals("..")) throw new NativeFailure("INVALID_API_PATH");
        if (control(decoded(query))) throw new NativeFailure("INVALID_API_PATH");
    }
    public static byte[] decode(String value, int limit, String tooLarge) throws NativeFailure {
        if (value == null) throw new NativeFailure("INVALID_BASE64");
        if (value.length() > ((long) limit + 2) / 3 * 4) throw new NativeFailure(tooLarge);
        if (value.length() % 4 != 0) throw new NativeFailure("INVALID_BASE64");
        byte[] bytes;
        try { bytes = Base64.getDecoder().decode(value); } catch (IllegalArgumentException ignored) { throw new NativeFailure("INVALID_BASE64"); }
        if (bytes.length > limit) throw new NativeFailure(tooLarge);
        if (!Base64.getEncoder().encodeToString(bytes).equals(value)) throw new NativeFailure("INVALID_BASE64");
        return bytes;
    }
    public static Request request(String id, String path, String method, Map<String,String> headers, String body, MetadataValidator validator) throws NativeFailure {
        requestId(id); path(path);
        if (!"GET".equals(method) && !"POST".equals(method) && !"PUT".equals(method) && !"DELETE".equals(method)) throw new NativeFailure("INVALID_API_METHOD");
        Map<String,String> clean = new LinkedHashMap<>();
        if (headers.size() > 3) throw new NativeFailure("INVALID_API_HEADER");
        for (Map.Entry<String,String> entry : headers.entrySet()) {
            String name = entry.getKey().toLowerCase(Locale.ROOT), value = entry.getValue();
            if (value == null || control(value) || clean.containsKey(name)) throw new NativeFailure("INVALID_API_HEADER");
            switch (name) {
                case "content-type": if (!value.equals("application/json") && !value.equals("application/pdf")) throw new NativeFailure("INVALID_API_HEADER"); break;
                case "idempotency-key": try { requestId(value); } catch (NativeFailure ignored) { throw new NativeFailure("INVALID_API_HEADER"); } break;
                case "x-evidence-metadata":
                    try { if (!validator.valid(decode(value, 12 * 1024, "INVALID_API_HEADER"))) throw new NativeFailure("INVALID_API_HEADER"); }
                    catch (NativeFailure ignored) { throw new NativeFailure("INVALID_API_HEADER"); } break;
                default: throw new NativeFailure("INVALID_API_HEADER");
            }
            clean.put(name, value);
        }
        if (body != null && (method.equals("GET") || !clean.containsKey("content-type"))) throw new NativeFailure("INVALID_API_BODY");
        return new Request(id.toLowerCase(Locale.ROOT), path, method, clean, body == null ? new byte[0] : decode(body, MAX_REQUEST_BYTES, "REQUEST_TOO_LARGE"));
    }
    public static URI externalUrl(String value) throws NativeFailure {
        if (value == null || value.length() > 8192 || value.indexOf('\\') >= 0 || control(value)) throw new NativeFailure("INVALID_EXTERNAL_URL");
        try {
            URI uri = new URI(value);
            if (!("http".equalsIgnoreCase(uri.getScheme()) || "https".equalsIgnoreCase(uri.getScheme())) || uri.getHost() == null || uri.getRawUserInfo() != null) throw new NativeFailure("INVALID_EXTERNAL_URL");
            return uri;
        } catch (java.net.URISyntaxException ignored) { throw new NativeFailure("INVALID_EXTERNAL_URL"); }
    }
    public static boolean allowedNavigation(String value) {
        try {
            URI uri = new URI(value);
            return "https".equals(uri.getScheme()) && "localhost".equals(uri.getHost()) && uri.getRawUserInfo() == null && (uri.getPort() == -1 || uri.getPort() == 443);
        } catch (Exception ignored) { return false; }
    }
    public static String download(String name, String mime) throws NativeFailure {
        if (name == null || name.isEmpty() || name.getBytes(StandardCharsets.UTF_8).length > 180 || name.startsWith(".") || name.endsWith(".") || name.endsWith(" ") || control(name) || name.matches(".*[/\\\\:<>\"|?*].*")) throw new NativeFailure("INVALID_DOWNLOAD_NAME");
        String stem = name.split("\\.", -1)[0].toUpperCase(Locale.ROOT);
        if (stem.matches("CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9]")) throw new NativeFailure("INVALID_DOWNLOAD_NAME");
        String type = mime == null ? "" : mime.split(";", -1)[0].trim();
        String extension = name.substring(name.lastIndexOf('.') + 1);
        if ((extension.equals("md") && (type.equals("text/markdown") || type.equals("text/plain"))) || (extension.equals("html") && type.equals("text/html")) || (extension.equals("pdf") && type.equals("application/pdf"))) return type;
        throw new NativeFailure("INVALID_DOWNLOAD_TYPE");
    }
}
