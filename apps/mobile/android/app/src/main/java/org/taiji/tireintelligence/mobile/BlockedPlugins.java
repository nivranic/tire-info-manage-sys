package org.taiji.tireintelligence.mobile;

import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/** Core plugins are always registered by Capacitor; replace their public handles explicitly. */
public final class BlockedPlugins {
    private BlockedPlugins() {}
    public static class Denied extends Plugin {
        private void deny(PluginCall call) { call.reject("NATIVE_CAPABILITY_DENIED", "NATIVE_CAPABILITY_DENIED"); }
        @PluginMethod public void request(PluginCall call) { deny(call); }
        @PluginMethod public void get(PluginCall call) { deny(call); }
        @PluginMethod public void post(PluginCall call) { deny(call); }
        @PluginMethod public void put(PluginCall call) { deny(call); }
        @PluginMethod public void patch(PluginCall call) { deny(call); }
        @PluginMethod public void delete(PluginCall call) { deny(call); }
        @PluginMethod public void getCookies(PluginCall call) { deny(call); }
        @PluginMethod public void setCookie(PluginCall call) { deny(call); }
        @PluginMethod public void deleteCookie(PluginCall call) { deny(call); }
        @PluginMethod public void clearCookies(PluginCall call) { deny(call); }
        @PluginMethod public void clearAllCookies(PluginCall call) { deny(call); }
        @PluginMethod public void setServerAssetPath(PluginCall call) { deny(call); }
        @PluginMethod public void setServerBasePath(PluginCall call) { deny(call); }
        @PluginMethod public void getServerBasePath(PluginCall call) { deny(call); }
        @PluginMethod public void persistServerBasePath(PluginCall call) { deny(call); }
        @PluginMethod public void setStyle(PluginCall call) { deny(call); }
        @PluginMethod public void show(PluginCall call) { deny(call); }
        @PluginMethod public void hide(PluginCall call) { deny(call); }
        @PluginMethod public void setAnimation(PluginCall call) { deny(call); }
    }
    @CapacitorPlugin(name = "CapacitorHttp") public static final class Http extends Denied {}
    @CapacitorPlugin(name = "CapacitorCookies") public static final class Cookies extends Denied {}
    @CapacitorPlugin(name = "WebView") public static final class WebView extends Denied {}
    @CapacitorPlugin(name = "SystemBars") public static final class SystemBars extends Denied {}
}
