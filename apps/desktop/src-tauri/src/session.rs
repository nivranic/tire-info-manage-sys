//! This store can access only one application-owned credential. It never enumerates credentials.
use crate::security::{request_id, LaunchConfig, NativeResult};
use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};
use tokio::sync::Mutex as AsyncMutex;

pub const COOKIE_NAME: &str = "tire_local_session";
const SERVICE: &str = "org.taiji.tireintelligence.desktop.session";

pub trait SessionStore: Send + Sync {
    fn load(&self) -> NativeResult<Option<String>>;
    fn save(&self, cookie: Option<&str>) -> NativeResult<()>;
    fn delete(&self) -> NativeResult<()>;
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredSession {
    version: u8,
    cookie: Option<String>,
}

#[cfg(any(target_os = "windows", target_os = "macos"))]
pub struct OsSessionStore {
    entry: keyring::Entry,
}

#[cfg(any(target_os = "windows", target_os = "macos"))]
impl OsSessionStore {
    pub fn open(config: &LaunchConfig) -> NativeResult<Arc<dyn SessionStore>> {
        let entry = keyring::Entry::new(SERVICE, &config.store_account())
            .map_err(|_| "SESSION_STORE_UNAVAILABLE")?;
        Ok(Arc::new(Self { entry }))
    }
}

#[cfg(any(target_os = "windows", target_os = "macos"))]
impl SessionStore for OsSessionStore {
    fn load(&self) -> NativeResult<Option<String>> {
        let raw = match self.entry.get_password() {
            Ok(raw) => raw,
            Err(keyring::Error::NoEntry) => return Ok(None),
            Err(_) => return Err("SESSION_STORE_READ_FAILED"),
        };
        if raw.len() > 1024 {
            return Err("SESSION_STORE_INVALID");
        }
        let saved: StoredSession =
            serde_json::from_str(&raw).map_err(|_| "SESSION_STORE_INVALID")?;
        if saved.version != 1 {
            return Err("SESSION_STORE_INVALID");
        }
        if let Some(cookie) = &saved.cookie {
            request_id(cookie).map_err(|_| "SESSION_STORE_INVALID")?;
        }
        Ok(saved.cookie)
    }

    fn save(&self, cookie: Option<&str>) -> NativeResult<()> {
        let raw = serde_json::to_string(&StoredSession {
            version: 1,
            cookie: cookie.map(str::to_owned),
        })
        .map_err(|_| "SESSION_STORE_WRITE_FAILED")?;
        self.entry
            .set_password(&raw)
            .map_err(|_| "SESSION_STORE_WRITE_FAILED")
    }

    fn delete(&self) -> NativeResult<()> {
        match self.entry.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(_) => Err("SESSION_STORE_DELETE_FAILED"),
        }
    }
}

#[cfg(not(any(target_os = "windows", target_os = "macos")))]
pub struct OsSessionStore;

#[cfg(not(any(target_os = "windows", target_os = "macos")))]
impl OsSessionStore {
    pub fn open(_config: &LaunchConfig) -> NativeResult<Arc<dyn SessionStore>> {
        Err("SESSION_STORE_UNSUPPORTED_PLATFORM")
    }
}

pub struct SessionData {
    pub cookie: Option<String>,
    pub bootstrapped: bool,
    pub generation: u64,
}

pub struct Session {
    store: Arc<dyn SessionStore>,
    pub data: Arc<AsyncMutex<SessionData>>,
    failure: Mutex<Option<&'static str>>,
}

impl Session {
    pub fn new(store: Arc<dyn SessionStore>) -> Self {
        let loaded = store.load().and_then(|cookie| {
            if let Some(value) = &cookie {
                request_id(value).map_err(|_| "SESSION_STORE_INVALID")?;
            }
            // Persisting an empty envelope also verifies write access on first launch.
            // No plaintext/ephemeral fallback is permitted if the native store is unavailable.
            store.save(cookie.as_deref())?;
            Ok(cookie)
        });
        let (cookie, failure) = match loaded {
            Ok(cookie) => (cookie, None),
            Err(error) => (None, Some(error)),
        };
        Self {
            store,
            data: Arc::new(AsyncMutex::new(SessionData {
                cookie,
                bootstrapped: false,
                generation: 0,
            })),
            failure: Mutex::new(failure),
        }
    }

    pub fn error(&self) -> Option<&'static str> {
        match self.failure.lock() {
            Ok(value) => *value,
            Err(_) => Some("SESSION_STORE_UNAVAILABLE"),
        }
    }

    pub fn check(&self) -> NativeResult<()> {
        match self.error() {
            Some(error) => Err(error),
            None => Ok(()),
        }
    }

    pub async fn recover(&self) -> NativeResult<()> {
        let mut data = self.data.lock().await;
        if self.error().is_none() {
            return Ok(());
        }
        // Retry reloads the last durable session without deleting or minting a cookie.
        let loaded = self.store.load().and_then(|cookie| {
            if let Some(value) = &cookie {
                request_id(value).map_err(|_| "SESSION_STORE_INVALID")?;
            }
            self.store.save(cookie.as_deref())?;
            Ok(cookie)
        });
        match loaded {
            Ok(cookie) => {
                data.generation = data
                    .generation
                    .checked_add(1)
                    .ok_or("SESSION_GENERATION_EXHAUSTED")?;
                data.cookie = cookie;
                data.bootstrapped = false;
                *self
                    .failure
                    .lock()
                    .map_err(|_| "SESSION_STORE_UNAVAILABLE")? = None;
                Ok(())
            }
            Err(error) => {
                *self
                    .failure
                    .lock()
                    .map_err(|_| "SESSION_STORE_UNAVAILABLE")? = Some(error);
                Err(error)
            }
        }
    }

    pub fn persist(&self, data: &mut SessionData, cookie: Option<String>) -> NativeResult<()> {
        if data.cookie == cookie {
            return self.check();
        }
        data.generation = data
            .generation
            .checked_add(1)
            .ok_or("SESSION_GENERATION_EXHAUSTED")?;
        if let Err(error) = self.store.save(cookie.as_deref()) {
            if let Ok(mut failure) = self.failure.lock() {
                *failure = Some(error);
            }
            data.cookie = None;
            data.bootstrapped = false;
            return Err(error);
        }
        data.cookie = cookie;
        Ok(())
    }

    pub async fn reset(&self) -> NativeResult<()> {
        let mut data = self.data.lock().await;
        data.generation = data
            .generation
            .checked_add(1)
            .ok_or("SESSION_GENERATION_EXHAUSTED")?;
        if let Err(error) = self.store.delete() {
            if let Ok(mut failure) = self.failure.lock() {
                *failure = Some(error);
            }
            return Err(error);
        }
        data.cookie = None;
        data.bootstrapped = false;
        if let Ok(mut failure) = self.failure.lock() {
            *failure = None;
        }
        Ok(())
    }
}
