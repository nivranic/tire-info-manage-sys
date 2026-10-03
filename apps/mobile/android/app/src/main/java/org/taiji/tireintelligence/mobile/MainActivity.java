package org.taiji.tireintelligence.mobile;

import android.graphics.Color;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.ServiceWorkerClient;
import android.webkit.ServiceWorkerController;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.widget.TextView;
import androidx.activity.OnBackPressedCallback;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.core.view.WindowInsetsControllerCompat;
import androidx.webkit.WebViewFeature;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.BridgeWebViewClient;
import com.getcapacitor.CapConfig;
import com.getcapacitor.JSObject;
import com.getcapacitor.ServerPath;
import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.net.CookieHandler;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

public final class MainActivity extends BridgeActivity {
    private volatile boolean trustedDocument;
    private final Set<String> assetPaths = new HashSet<>();
    private ValueCallback<android.net.Uri[]> pdfCallback;
    private final ActivityResultLauncher<String[]> pdfPicker = registerForActivityResult(new ActivityResultContracts.OpenDocument(), uri -> {
        ValueCallback<android.net.Uri[]> callback = pdfCallback; pdfCallback = null;
        if (callback == null) return;
        if (uri == null || !"content".equals(uri.getScheme())) { callback.onReceiveValue(null); return; }
        // The OS grants this one user-selected document; no storage permission or persistable grant.
        try (android.database.Cursor cursor = getContentResolver().query(uri, new String[]{android.provider.OpenableColumns.DISPLAY_NAME, android.provider.OpenableColumns.SIZE}, null, null, null)) {
            if (cursor == null || !cursor.moveToFirst() || !cursor.getString(0).toLowerCase(java.util.Locale.ROOT).endsWith(".pdf")
                    || cursor.isNull(1) || cursor.getLong(1) < 0 || cursor.getLong(1) > 8 * 1024 * 1024) { callback.onReceiveValue(null); return; }
            callback.onReceiveValue(new android.net.Uri[]{uri});
        } catch (Exception ignored) { callback.onReceiveValue(null); }
    });
    public boolean isTrustedDocument() { return trustedDocument; }
    @Override public void onDestroy() {
        ValueCallback<android.net.Uri[]> callback = pdfCallback; pdfCallback = null;
        if (callback != null) callback.onReceiveValue(null);
        super.onDestroy();
    }
    @Override protected void onCreate(Bundle savedInstanceState) {
        // Native constants determine the privileged origin; asset config cannot enable remote URLs.
        config = new CapConfig.Builder(this).setHostname("localhost").setAndroidScheme("https").setServerUrl(null)
                .setAllowNavigation(new String[0]).setAllowMixedContent(false).setUseLegacyBridge(false)
                .setResolveServiceWorkerRequests(false).setLoggingEnabled(false).setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
                .setPluginsConfiguration(new JSObject().put("SystemBars", new JSObject().put("insetsHandling", "disable"))).create();
        bridgeBuilder.setServerPath(new ServerPath(ServerPath.PathType.ASSET_PATH, "public"));
        registerPlugin(BlockedPlugins.Http.class); registerPlugin(BlockedPlugins.Cookies.class); registerPlugin(BlockedPlugins.WebView.class); registerPlugin(BlockedPlugins.SystemBars.class); registerPlugin(TireNativePlugin.class);
        // Never restore a native webview server path or navigation from a launch intent.
        getIntent().replaceExtras((Bundle) null);
        getSharedPreferences("CapWebViewSettings", MODE_PRIVATE).edit().remove("serverBasePath").apply();
        super.onCreate(null);
        if (bridge == null) return;
        hardenWebView();
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override public void handleOnBackPressed() { if (trustedDocument) ((TireNativePlugin) bridge.getPlugin("TireNative").getInstance()).requestBack(); else moveTaskToBack(true); }
        });
    }
    private void listAssets(String path) throws Exception {
        String[] entries = getAssets().list(path);
        if (entries == null) return;
        for (String entry : entries) {
            String child = path + "/" + entry; String[] descendants = getAssets().list(child);
            if (descendants != null && descendants.length > 0) listAssets(child); else assetPaths.add("/" + child.substring("public/".length()));
        }
    }
    private boolean allowedAsset(String url) {
        if (!NativePolicy.allowedNavigation(url)) return false;
        try {
            String raw = new java.net.URI(url).getRawPath();
            // The real asset inventory excludes all Capacitor HTTP/content/file proxy namespaces.
            if (raw == null || raw.contains("%") || raw.contains("\\") || raw.contains("..") || raw.startsWith("/_capacitor_")) return false;
            return raw.equals("/") || assetPaths.contains(raw);
        } catch (Exception ignored) { return false; }
    }
    private static WebResourceResponse denied() { return new WebResourceResponse("text/plain", "UTF-8", 403, "Blocked", Collections.singletonMap("Cache-Control", "no-store"), new ByteArrayInputStream(new byte[0])); }
    private void hardenWebView() {
        WebView view = bridge.getWebView();
        view.removeJavascriptInterface("CapacitorHttpAndroidInterface"); view.removeJavascriptInterface("CapacitorCookiesAndroidInterface");
        // The modern, main-frame-only WebMessageListener remains; remove any silent legacy fallback.
        view.removeJavascriptInterface("androidBridge");
        CookieHandler.setDefault(null); CookieManager.getInstance().setAcceptCookie(false); CookieManager.getInstance().setAcceptThirdPartyCookies(view, false);
        CookieManager.getInstance().removeAllCookies(null);
        WebSettings settings = view.getSettings(); settings.setAllowFileAccess(false); settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW); settings.setJavaScriptCanOpenWindowsAutomatically(false); settings.setSupportMultipleWindows(true);
        settings.setGeolocationEnabled(false); settings.setMediaPlaybackRequiresUserGesture(true); settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        try { listAssets("public"); } catch (Exception ignored) { failClosed("安装包资源不可用，请重新安装胎迹。"); return; }
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) { failClosed("系统 WebView 版本过旧，请更新 Android System WebView 后重试。"); return; }
        bridge.setWebViewClient(new BridgeWebViewClient(bridge) {
            @Override public WebResourceResponse shouldInterceptRequest(WebView current, WebResourceRequest request) {
                return "GET".equals(request.getMethod()) && allowedAsset(request.getUrl().toString()) ? super.shouldInterceptRequest(current, request) : denied();
            }
            @Override public boolean shouldOverrideUrlLoading(WebView current, WebResourceRequest request) { return !request.isForMainFrame() || !allowedAsset(request.getUrl().toString()); }
            @Override public boolean shouldOverrideUrlLoading(WebView current, String url) { return !allowedAsset(url); }
            @Override public void onPageStarted(WebView current, String url, android.graphics.Bitmap icon) {
                com.getcapacitor.PluginHandle handle = bridge.getPlugin("TireNative");
                if (handle != null && handle.getInstance() instanceof TireNativePlugin) ((TireNativePlugin) handle.getInstance()).documentStarted();
                trustedDocument = allowedAsset(url); if (!trustedDocument) { current.stopLoading(); return; } super.onPageStarted(current, url, icon);
            }
        });
        // Service workers never inherit Capacitor's special native file/HTTP proxy implementation.
        ServiceWorkerController.getInstance().setServiceWorkerClient(new ServiceWorkerClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebResourceRequest request) { return denied(); }
        });
        ServiceWorkerController.getInstance().getServiceWorkerWebSettings().setBlockNetworkLoads(true);
        ServiceWorkerController.getInstance().getServiceWorkerWebSettings().setAllowContentAccess(false);
        ServiceWorkerController.getInstance().getServiceWorkerWebSettings().setAllowFileAccess(false);
        view.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onCreateWindow(WebView current, boolean dialog, boolean gesture, android.os.Message result) { return false; }
            @Override public void onPermissionRequest(PermissionRequest request) { request.deny(); }
            @Override public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) { callback.invoke(origin, false, false); }
            @Override public boolean onShowFileChooser(WebView current, ValueCallback<android.net.Uri[]> callback, FileChooserParams parameters) {
                boolean pdfOnly = parameters.getAcceptTypes().length > 0;
                for (String types : parameters.getAcceptTypes()) for (String type : types.split(",")) {
                    if (!type.trim().equalsIgnoreCase("application/pdf") && !type.trim().equalsIgnoreCase(".pdf")) pdfOnly = false;
                }
                if (!trustedDocument || !pdfOnly || parameters.isCaptureEnabled() || parameters.getMode() != FileChooserParams.MODE_OPEN || pdfCallback != null) { callback.onReceiveValue(null); return true; }
                pdfCallback = callback;
                try { pdfPicker.launch(new String[]{"application/pdf"}); }
                catch (Exception ignored) { pdfCallback = null; callback.onReceiveValue(null); }
                return true;
            }
        });
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        ViewCompat.setOnApplyWindowInsetsListener(view, (current, insets) -> {
            Insets system = insets.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout());
            Insets ime = insets.getInsets(WindowInsetsCompat.Type.ime());
            // Capacitor's WebView is a CoordinatorLayout child with margin layout parameters.
            // Margins resize Chromium's viewport; WebView padding leaves its CSS viewport full-screen.
            android.view.ViewGroup.MarginLayoutParams layout = (android.view.ViewGroup.MarginLayoutParams) current.getLayoutParams();
            int bottom = Math.max(system.bottom, ime.bottom);
            if (layout.leftMargin != system.left || layout.topMargin != system.top || layout.rightMargin != system.right || layout.bottomMargin != bottom) {
                layout.setMargins(system.left, system.top, system.right, bottom); current.setLayoutParams(layout);
            }
            if (current.getPaddingLeft() != 0 || current.getPaddingTop() != 0 || current.getPaddingRight() != 0 || current.getPaddingBottom() != 0) current.setPadding(0, 0, 0, 0);
            return WindowInsetsCompat.CONSUMED;
        });
        view.post(() -> { setSystemTheme(false); ViewCompat.requestApplyInsets(view); });
    }
    private void failClosed(String message) {
        trustedDocument = false; bridge.getWebView().stopLoading(); bridge.getWebView().getSettings().setJavaScriptEnabled(false);
        TextView text = new TextView(this); text.setText(message); text.setTextSize(18); text.setPadding(32, 80, 32, 32); setContentView(text);
    }
    public void setSystemTheme(boolean dark) {
        int color = Color.parseColor(dark ? "#191d1c" : "#f6f5f1");
        getWindow().getDecorView().setBackgroundColor(color); bridge.getWebView().setBackgroundColor(color);
        getWindow().setStatusBarColor(color); getWindow().setNavigationBarColor(color);
        WindowInsetsControllerCompat controller = WindowCompat.getInsetsController(getWindow(), bridge.getWebView());
        controller.setAppearanceLightStatusBars(!dark); controller.setAppearanceLightNavigationBars(!dark);
    }
}
