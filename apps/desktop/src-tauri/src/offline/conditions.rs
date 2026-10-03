//! Native observations contain no SSID, adapter identity or credential material.
use crate::security::NativeResult;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Conditions {
    pub network: String,
    pub power: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Capabilities {
    pub schema: String,
    pub scheduler: String,
    pub wifi: bool,
    pub external_power: bool,
    pub battery_charging: bool,
    pub min_interval_seconds: u64,
    pub max_interval_seconds: u64,
    pub host_build: String,
    pub validator_version: String,
}

pub const VALIDATOR_VERSION: &str = "offline-validator@2";
pub const HOST_BUILD: &str = env!("OFFLINE_HOST_BUILD");

pub fn capabilities() -> Capabilities {
    let supported = cfg!(target_os = "windows");
    Capabilities {
        schema: "device-sync-capabilities@1".into(),
        scheduler: if supported {
            "native_app_open"
        } else {
            "unsupported"
        }
        .into(),
        wifi: supported,
        external_power: supported,
        battery_charging: supported,
        min_interval_seconds: 900,
        max_interval_seconds: 604800,
        host_build: HOST_BUILD.into(),
        validator_version: VALIDATOR_VERSION.into(),
    }
}

#[derive(Clone, Copy, Default)]
pub struct Sample {
    pub wifi: Option<bool>,
    pub external_power: Option<bool>,
    pub battery_charging: Option<bool>,
}

impl Conditions {
    pub fn validate(&self) -> NativeResult<()> {
        if !matches!(self.network.as_str(), "any" | "wifi")
            || !matches!(
                self.power.as_str(),
                "any" | "external_power" | "battery_charging"
            )
        {
            return Err("OFFLINE_SYNC_CONDITIONS_INVALID");
        }
        let caps = capabilities();
        if (self.network == "wifi" && !caps.wifi)
            || (self.power == "external_power" && !caps.external_power)
            || (self.power == "battery_charging" && !caps.battery_charging)
        {
            return Err("OFFLINE_SYNC_CONDITIONS_UNSUPPORTED");
        }
        Ok(())
    }
    pub fn met(&self, sample: Sample) -> bool {
        (self.network == "any" || (self.network == "wifi" && sample.wifi == Some(true)))
            && match self.power.as_str() {
                "any" => true,
                "external_power" => sample.external_power == Some(true),
                "battery_charging" => sample.battery_charging == Some(true),
                _ => false,
            }
    }
}

pub fn power_sample(ac: u8, battery: u8) -> Sample {
    Sample {
        wifi: None,
        external_power: match ac {
            0 => Some(false),
            1 => Some(true),
            _ => None,
        },
        battery_charging: if battery == 255 {
            None
        } else {
            Some(battery & 8 != 0)
        },
    }
}

#[cfg(target_os = "windows")]
pub fn sample() -> Sample {
    use windows::{
        Networking::Connectivity::NetworkInformation,
        Win32::System::{
            Power::{GetSystemPowerStatus, SYSTEM_POWER_STATUS},
            WinRT::{RoInitialize, RoUninitialize, RO_INIT_MULTITHREADED},
        },
    };
    let mut status = SYSTEM_POWER_STATUS::default();
    let mut sample = if unsafe { GetSystemPowerStatus(&mut status) }.is_ok() {
        power_sample(status.ACLineStatus, status.BatteryFlag)
    } else {
        Sample::default()
    };
    if unsafe { RoInitialize(RO_INIT_MULTITHREADED) }.is_ok() {
        struct Com;
        impl Drop for Com {
            fn drop(&mut self) {
                unsafe { RoUninitialize() };
            }
        }
        let _com = Com;
        sample.wifi = NetworkInformation::GetInternetConnectionProfile()
            .and_then(|profile| profile.IsWlanConnectionProfile())
            .ok();
    }
    sample
}
#[cfg(not(target_os = "windows"))]
pub fn sample() -> Sample {
    Sample::default()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(target_os = "windows")]
    #[test]
    fn actual_windows_sensor_probe_uses_a_blocking_mta_without_device_identity() {
        let observed = std::thread::spawn(sample).join().unwrap();
        println!(
            "{}",
            serde_json::json!({"windows_native_conditions":{"wifi":observed.wifi,"external_power":observed.external_power,"battery_charging":observed.battery_charging},"ssid_or_mac_read":false})
        );
        assert_eq!(capabilities().scheduler, "native_app_open");
        assert!(
            capabilities().wifi && capabilities().external_power && capabilities().battery_charging
        );
    }
    #[test]
    fn ac_and_actual_charging_are_distinct_and_unknown_is_not_charging() {
        let ac = power_sample(1, 1);
        assert_eq!(ac.external_power, Some(true));
        assert_eq!(ac.battery_charging, Some(false));
        let battery = power_sample(0, 8);
        assert_eq!(battery.external_power, Some(false));
        assert_eq!(battery.battery_charging, Some(true));
        let unknown = power_sample(255, 255);
        assert_eq!(unknown.external_power, None);
        assert_eq!(unknown.battery_charging, None);
    }
    #[test]
    fn wifi_and_power_use_and_with_unknown_blocked() {
        let c = Conditions {
            network: "wifi".into(),
            power: "battery_charging".into(),
        };
        assert!(!c.met(Sample::default()));
        assert!(!c.met(Sample {
            wifi: Some(true),
            external_power: Some(true),
            battery_charging: Some(false)
        }));
        assert!(c.met(Sample {
            wifi: Some(true),
            external_power: Some(false),
            battery_charging: Some(true)
        }));
    }
}
