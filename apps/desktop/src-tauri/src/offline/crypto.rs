use crate::security::NativeResult;
use aes_gcm::{
    aead::{Aead, KeyInit, Payload},
    Aes256Gcm, Nonce,
};
use rand_core::{OsRng, RngCore};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

const MAGIC: &[u8; 8] = b"TIOFFL01";
pub const OVERHEAD: usize = 8 + 12 + 16;

pub fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub fn random_key() -> NativeResult<Zeroizing<[u8; 32]>> {
    let mut key = Zeroizing::new([0; 32]);
    OsRng
        .try_fill_bytes(key.as_mut())
        .map_err(|_| "OFFLINE_KEY_UNAVAILABLE")?;
    Ok(key)
}

pub fn seal(key: &[u8; 32], aad: &[u8], clear: &[u8]) -> NativeResult<Vec<u8>> {
    let mut nonce = [0_u8; 12];
    OsRng
        .try_fill_bytes(&mut nonce)
        .map_err(|_| "OFFLINE_KEY_UNAVAILABLE")?;
    let cipher = Aes256Gcm::new_from_slice(key).map_err(|_| "OFFLINE_KEY_UNAVAILABLE")?;
    let ciphertext = cipher
        .encrypt(Nonce::from_slice(&nonce), Payload { msg: clear, aad })
        .map_err(|_| "OFFLINE_ENCRYPTION_FAILED")?;
    let mut encoded = Vec::with_capacity(OVERHEAD + clear.len());
    encoded.extend_from_slice(MAGIC);
    encoded.extend_from_slice(&nonce);
    encoded.extend_from_slice(&ciphertext);
    Ok(encoded)
}

pub fn open(
    key: &[u8; 32],
    aad: &[u8],
    encoded: &[u8],
    limit: usize,
) -> NativeResult<Zeroizing<Vec<u8>>> {
    if encoded.len() < OVERHEAD
        || encoded.len() > limit.saturating_add(OVERHEAD)
        || &encoded[..8] != MAGIC
    {
        return Err("OFFLINE_PACK_CORRUPT");
    }
    let cipher = Aes256Gcm::new_from_slice(key).map_err(|_| "OFFLINE_KEY_UNAVAILABLE")?;
    let clear = cipher
        .decrypt(
            Nonce::from_slice(&encoded[8..20]),
            Payload {
                msg: &encoded[20..],
                aad,
            },
        )
        .map_err(|_| "OFFLINE_PACK_CORRUPT")?;
    if clear.len() > limit {
        return Err("OFFLINE_PACK_TOO_LARGE");
    }
    Ok(Zeroizing::new(clear))
}

pub trait KeyStore: Send + Sync {
    fn load(&self) -> NativeResult<Option<Zeroizing<[u8; 32]>>>;
    fn save(&self, key: &[u8; 32]) -> NativeResult<()>;
}

#[cfg(any(target_os = "windows", target_os = "macos"))]
pub struct OsKeyStore(keyring::Entry);

#[cfg(any(target_os = "windows", target_os = "macos"))]
impl OsKeyStore {
    pub fn new(account: &str) -> NativeResult<Self> {
        keyring::Entry::new("org.taiji.tireintelligence.desktop.offline.v1", account)
            .map(Self)
            .map_err(|_| "OFFLINE_KEY_UNAVAILABLE")
    }
}

#[cfg(any(target_os = "windows", target_os = "macos"))]
impl KeyStore for OsKeyStore {
    fn load(&self) -> NativeResult<Option<Zeroizing<[u8; 32]>>> {
        let bytes = match self.0.get_secret() {
            Ok(bytes) => Zeroizing::new(bytes),
            Err(keyring::Error::NoEntry) => return Ok(None),
            Err(_) => return Err("OFFLINE_KEY_UNAVAILABLE"),
        };
        if bytes.len() != 32 {
            return Err("OFFLINE_KEY_INVALID");
        }
        let mut key = Zeroizing::new([0; 32]);
        key.copy_from_slice(&bytes);
        Ok(Some(key))
    }
    fn save(&self, key: &[u8; 32]) -> NativeResult<()> {
        self.0
            .set_secret(key)
            .map_err(|_| "OFFLINE_KEY_UNAVAILABLE")
    }
}
