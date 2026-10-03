package org.taiji.tireintelligence.mobile;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.BatteryManager;
import org.json.JSONObject;

/** Default transport only; no SSID, BSSID, MAC, location or Wi-Fi identifiers. */
final class OfflineSyncConditions {
    static final class Sample {
        final Boolean wifi, externalPower, batteryCharging;
        Sample(Boolean wifi, Boolean externalPower, Boolean batteryCharging) {
            this.wifi = wifi; this.externalPower = externalPower; this.batteryCharging = batteryCharging;
        }
    }
    static void validate(JSONObject conditions) throws NativeFailure {
        OfflinePackageValidator.keys(conditions, "network", "power");
        String network = OfflinePackageValidator.text(conditions, "network", 20);
        String power = OfflinePackageValidator.text(conditions, "power", 30);
        if (!(network.equals("any") || network.equals("wifi")) ||
            !(power.equals("any") || power.equals("external_power") || power.equals("battery_charging"))) {
            throw new NativeFailure("OFFLINE_INVALID_ARGUMENT");
        }
    }
    /** Null means unknown and cannot satisfy an explicitly requested condition. */
    static String blocked(JSONObject conditions, Sample sample) throws NativeFailure {
        validate(conditions);
        boolean wifi = "wifi".equals(conditions.optString("network"));
        String power = conditions.optString("power");
        Boolean requestedPower = power.equals("external_power") ? sample.externalPower : sample.batteryCharging;
        if ((wifi && sample.wifi == null) || (!power.equals("any") && requestedPower == null)) {
            return "OFFLINE_SYNC_CONDITION_UNKNOWN";
        }
        if ((wifi && !Boolean.TRUE.equals(sample.wifi)) || (!power.equals("any") && !Boolean.TRUE.equals(requestedPower))) {
            return "OFFLINE_SYNC_CONDITION_UNMET";
        }
        return null;
    }
    static Sample sample(Context context) {
        Boolean wifi = null, external = null, charging = null;
        try {
            ConnectivityManager manager = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
            Network network = manager == null ? null : manager.getActiveNetwork();
            NetworkCapabilities caps = network == null ? null : manager.getNetworkCapabilities(network);
            if (caps != null && !caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) {
                wifi = caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) &&
                    !caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) &&
                    !caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET);
            }
        } catch (RuntimeException ignored) { /* Permission, capability or service absence stays unknown. */ }
        try {
            Intent battery = context.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            if (battery != null) {
                int plugged = battery.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1);
                // AC/USB/WIRELESS/DOCK bitmask; unrecognised bits cannot prove external power.
                if (plugged >= 0 && (plugged & ~15) == 0) external = plugged != 0;
                int status = battery.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
                if (battery.hasExtra(BatteryManager.EXTRA_PRESENT) && !battery.getBooleanExtra(BatteryManager.EXTRA_PRESENT, true)) charging = false;
                else if (status == BatteryManager.BATTERY_STATUS_CHARGING) charging = true;
                else if (status == BatteryManager.BATTERY_STATUS_FULL || status == BatteryManager.BATTERY_STATUS_DISCHARGING ||
                    status == BatteryManager.BATTERY_STATUS_NOT_CHARGING) charging = false;
            }
        } catch (RuntimeException ignored) { /* Unknown never authorizes charging. */ }
        return new Sample(wifi, external, charging);
    }
}
