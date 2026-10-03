use super::{
    crypto::{self, KeyStore},
    index::Index,
    wire::{self, Context, Counts, Descriptor, Document, InstallRequest, Member},
    MAX_PACKAGE_BYTES, MAX_SLOTS, MAX_STORE_BYTES,
};
use crate::security::{LaunchConfig, NativeResult};
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::{Mutex, MutexGuard},
    time::Duration,
};
use zeroize::Zeroizing;

mod fallback;
pub use fallback::*;
mod sync;
pub use sync::*;

const SAFE_INTEGER: u64 = 9_007_199_254_740_990;
const MAX_METADATA_BYTES: usize = 64 * 1024;

#[derive(Clone, Serialize, Deserialize, Debug)]
#[serde(deny_unknown_fields)]
pub struct Slot {
    pub slot_id: String,
    pub generation: u64,
    pub package_id: String,
    pub sha256: String,
    pub byte_count: u64,
    pub title: String,
    pub created_at: String,
    pub installed_at: String,
    pub privacy_class: String,
    pub owner_scope_id: String,
    pub locked: bool,
    pub previous_owner: bool,
    pub counts: Counts,
}
#[derive(Serialize)]
pub struct Status {
    pub schema: &'static str,
    pub available: bool,
    pub state: &'static str,
    pub storage: &'static str,
    pub profile_id: Option<String>,
    pub owner_epoch: u64,
    pub total_bytes: u64,
    pub max_store_bytes: u64,
    pub max_package_bytes: usize,
    pub max_slots: usize,
    pub encryption: &'static str,
    pub persistence: &'static str,
    pub manual_updates: bool,
    pub background_updates: bool,
    pub error: Option<&'static str>,
}
impl Status {
    pub fn unavailable(error: &'static str) -> Self {
        Self::new(None, 0, 0, Some(error))
    }
    fn new(
        profile_id: Option<String>,
        owner_epoch: u64,
        total_bytes: u64,
        error: Option<&'static str>,
    ) -> Self {
        Self {
            schema: "offline-host@1",
            available: error.is_none(),
            state: if error.is_some() {
                "unavailable"
            } else {
                "ready"
            },
            storage: "native_encrypted_files",
            profile_id,
            owner_epoch,
            total_bytes,
            max_store_bytes: MAX_STORE_BYTES,
            max_package_bytes: MAX_PACKAGE_BYTES,
            max_slots: MAX_SLOTS,
            encryption: "os_secure_store",
            persistence: "app_private",
            manual_updates: true,
            background_updates: false,
            error,
        }
    }
}
#[derive(Serialize)]
pub struct List {
    pub schema: &'static str,
    pub data_state: &'static str,
    pub profile_id: String,
    pub owner_epoch: u64,
    pub items: Vec<Slot>,
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SlotRequest {
    pub slot_id: String,
    pub expected_generation: u64,
}
impl SlotRequest {
    fn validate(&self) -> NativeResult<()> {
        if !wire::uuid(&self.slot_id)
            || self.expected_generation == 0
            || self.expected_generation >= SAFE_INTEGER
        {
            return Err("OFFLINE_INVALID_ARGUMENT");
        }
        Ok(())
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchRequest {
    pub slot_id: String,
    pub expected_generation: u64,
    pub query: String,
    pub kind: Option<String>,
    pub limit: u64,
    pub offset: u64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReadRequest {
    pub slot_id: String,
    pub expected_generation: u64,
    pub document_id: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct UnlockRequest {
    pub slot_id: String,
    pub expected_generation: u64,
    pub allow_previous_owner: bool,
}
#[derive(Serialize)]
pub struct SearchResult {
    pub data_state: &'static str,
    pub slot: Slot,
    pub items: Vec<Document>,
    pub total: u64,
    pub offset: u64,
    pub limit: u64,
    pub has_more: bool,
}
#[derive(Serialize)]
pub struct ReadResult {
    pub data_state: &'static str,
    pub slot: Slot,
    pub document: Document,
    pub member: Option<Member>,
    pub context: Option<Context>,
}
#[derive(Serialize)]
pub struct RemoveResult {
    pub removed: bool,
    pub slot_id: String,
    pub generation: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Vault {
    profile_id: String,
    owner_epoch: u64,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Metadata {
    slot: Slot,
    descriptor: Descriptor,
    installed_epoch: u64,
    unlocked_epoch: Option<u64>,
    #[serde(default)]
    fallback_binding: Option<FallbackPackageBinding>,
}
struct Row {
    id: String,
    generation: u64,
    file_id: Option<String>,
    metadata: Option<Vec<u8>>,
}
struct Inner {
    connection: Connection,
    key: Zeroizing<[u8; 32]>,
    index: Option<Index>,
    fallback: fallback::Memory,
    sync: sync::Memory,
}
pub struct Store {
    root: PathBuf,
    namespace: String,
    inner: Mutex<Inner>,
    fallback_page: std::sync::atomic::AtomicU64,
}
// OS advisory lock survives asynchronous download but automatically releases on
// process exit. No stale lock-file deletion or PID inference is necessary.
pub struct InstallTicket {
    _lock: File,
    owner_epoch: u64,
}
pub struct StagedInstall {
    request: InstallRequest,
    slot: Slot,
    file_id: String,
    encoded: Vec<u8>,
    index: Option<Index>,
    path: PathBuf,
    published: bool,
    _ticket: InstallTicket,
}
impl Drop for StagedInstall {
    fn drop(&mut self) {
        if !self.published {
            let _ = fs::remove_file(&self.path);
        }
    }
}

fn db<T>(value: rusqlite::Result<T>) -> NativeResult<T> {
    value.map_err(|_| "OFFLINE_STORE_FAILED")
}
fn io<T>(value: std::io::Result<T>) -> NativeResult<T> {
    value.map_err(|_| "OFFLINE_STORE_FAILED")
}

impl Store {
    #[cfg(any(target_os = "windows", target_os = "macos"))]
    pub fn open(app_data: &Path, config: &LaunchConfig) -> NativeResult<Self> {
        let namespace = config.store_account();
        let root = app_data
            .join("offline-v1")
            .join(crypto::hash(namespace.as_bytes()));
        let keys = crypto::OsKeyStore::new(&namespace)?;
        Self::with_keys(root, namespace, &keys)
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    pub fn open(_app_data: &Path, _config: &LaunchConfig) -> NativeResult<Self> {
        Err("OFFLINE_UNSUPPORTED_PLATFORM")
    }
    pub(super) fn with_keys(
        root: PathBuf,
        namespace: String,
        keys: &dyn KeyStore,
    ) -> NativeResult<Self> {
        io(fs::create_dir_all(&root))?;
        if io(fs::symlink_metadata(&root))?.file_type().is_symlink() {
            return Err("OFFLINE_STORE_FAILED");
        }
        let catalog_path = root.join("catalog.sqlite3");
        if catalog_path.exists()
            && io(fs::symlink_metadata(&catalog_path))?
                .file_type()
                .is_symlink()
        {
            return Err("OFFLINE_STORE_FAILED");
        }
        let mut connection = db(Connection::open(&catalog_path))?;
        db(connection.busy_timeout(Duration::from_secs(3)))?;
        db(connection.execute_batch("PRAGMA trusted_schema=OFF; PRAGMA temp_store=MEMORY; PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL; CREATE TABLE IF NOT EXISTS vault(id INTEGER PRIMARY KEY CHECK(id=1), value BLOB NOT NULL); CREATE TABLE IF NOT EXISTS slots(id TEXT PRIMARY KEY,generation INTEGER NOT NULL CHECK(generation>0),file_id TEXT,metadata BLOB,CHECK((file_id IS NULL)=(metadata IS NULL))); CREATE TABLE IF NOT EXISTS fallback_audit(sequence INTEGER PRIMARY KEY,value BLOB NOT NULL); CREATE TABLE IF NOT EXISTS fallback_policy_control(id INTEGER PRIMARY KEY CHECK(id=1),value BLOB NOT NULL);"))?;
        let transaction = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let saved: Option<Vec<u8>> = db(transaction
            .query_row("SELECT value FROM vault WHERE id=1", [], |row| row.get(0))
            .optional())?;
        let has_slots = db(
            transaction.query_row("SELECT count(*) FROM slots", [], |row| row.get::<_, i64>(0))
        )? > 0;
        let mut has_packages = false;
        for entry in io(fs::read_dir(&root))? {
            has_packages |= io(entry)?
                .path()
                .extension()
                .is_some_and(|extension| extension == "pack");
        }
        // Missing control state is corruption, even when the OS key still
        // exists. Recreating epoch zero here could unlock an earlier owner.
        if saved.is_none() && (has_slots || has_packages) {
            return Err("OFFLINE_PACK_CORRUPT");
        }
        let existing_key = keys.load()?;
        if saved.is_none() && existing_key.is_some() {
            return Err("OFFLINE_PACK_CORRUPT");
        }
        let key = match existing_key {
            Some(key) => key,
            None if saved.is_some() || has_slots || has_packages => {
                return Err("OFFLINE_KEY_UNAVAILABLE")
            }
            None => {
                let key = crypto::random_key()?;
                keys.save(&key)?;
                key
            }
        };
        let state_aad = format!("offline-v1:{namespace}:state");
        if let Some(saved) = saved {
            let clear = crypto::open(&key, state_aad.as_bytes(), &saved, MAX_METADATA_BYTES)?;
            let vault: Vault =
                serde_json::from_slice(&clear).map_err(|_| "OFFLINE_PACK_CORRUPT")?;
            if !wire::uuid(&vault.profile_id) || vault.owner_epoch >= SAFE_INTEGER {
                return Err("OFFLINE_PACK_CORRUPT");
            }
        } else {
            // Fresh vaults start at owner_epoch 1, matching the web store and
            // the device-AI origin binding fence (owner = profile:epoch, the
            // TS/Rust fingerprint ports reject epoch 0 as an uninitialized
            // fence). Existing sealed vaults keep their persisted epoch.
            let vault = Vault {
                profile_id: uuid::Uuid::new_v4().to_string(),
                owner_epoch: 1,
            };
            let clear =
                Zeroizing::new(serde_json::to_vec(&vault).map_err(|_| "OFFLINE_STORE_FAILED")?);
            let sealed = crypto::seal(&key, state_aad.as_bytes(), &clear)?;
            db(transaction.execute("INSERT INTO vault(id,value) VALUES(1,?1)", [sealed]))?;
        }
        db(transaction.commit())?;
        let store = Self {
            root,
            namespace,
            inner: Mutex::new(Inner {
                connection,
                key,
                index: None,
                fallback: fallback::Memory::default(),
                sync: sync::Memory::default(),
            }),
            fallback_page: std::sync::atomic::AtomicU64::new(0),
        };
        // A damaged additive sync sidecar disables sync/read release gates;
        // it never removes the existing catalog or encrypted packages.
        let _ = store.initialize_fallback_runtime();
        let _ = store.initialize_sync();
        Ok(store)
    }
    fn lock(&self) -> NativeResult<MutexGuard<'_, Inner>> {
        self.inner.lock().map_err(|_| "OFFLINE_STORE_FAILED")
    }
    fn vault(&self, connection: &Connection, key: &[u8; 32]) -> NativeResult<Vault> {
        let encoded: Vec<u8> =
            db(connection.query_row("SELECT value FROM vault WHERE id=1", [], |row| row.get(0)))?;
        let clear = crypto::open(
            key,
            format!("offline-v1:{}:state", self.namespace).as_bytes(),
            &encoded,
            MAX_METADATA_BYTES,
        )?;
        serde_json::from_slice(&clear).map_err(|_| "OFFLINE_PACK_CORRUPT")
    }
    fn row(connection: &Connection, slot_id: &str) -> NativeResult<Option<Row>> {
        db(connection
            .query_row(
                "SELECT id,generation,file_id,metadata FROM slots WHERE id=?1",
                [slot_id],
                |row| {
                    Ok(Row {
                        id: row.get(0)?,
                        generation: row.get::<_, i64>(1)? as u64,
                        file_id: row.get(2)?,
                        metadata: row.get(3)?,
                    })
                },
            )
            .optional())
    }
    fn metadata(&self, row: &Row, key: &[u8; 32]) -> NativeResult<Metadata> {
        if !wire::uuid(&row.id)
            || row.generation == 0
            || row.generation >= SAFE_INTEGER
            || !row.file_id.as_deref().is_some_and(wire::uuid)
        {
            return Err("OFFLINE_PACK_CORRUPT");
        }
        let clear = crypto::open(
            key,
            self.metadata_aad(&row.id, row.generation).as_bytes(),
            row.metadata.as_deref().ok_or("OFFLINE_SLOT_NOT_FOUND")?,
            MAX_METADATA_BYTES,
        )?;
        let metadata: Metadata =
            serde_json::from_slice(&clear).map_err(|_| "OFFLINE_PACK_CORRUPT")?;
        if metadata.slot.slot_id != row.id
            || metadata.slot.generation != row.generation
            || metadata.slot.byte_count > MAX_PACKAGE_BYTES as u64
            || metadata.slot.package_id != metadata.descriptor.id
            || metadata.slot.sha256 != metadata.descriptor.sha256
            || metadata.slot.byte_count != metadata.descriptor.byte_count
            || metadata.slot.owner_scope_id != metadata.descriptor.owner_scope_id
            || metadata.slot.privacy_class != metadata.descriptor.privacy_class
            || metadata.slot.counts != metadata.descriptor.counts
            || metadata.slot.created_at != metadata.descriptor.content_created_at
            || !wire::hex(&metadata.slot.sha256)
            || metadata.installed_epoch >= SAFE_INTEGER
            || metadata.fallback_binding.as_ref().is_some_and(|binding| {
                binding.slot_id != row.id
                    || binding.generation != row.generation
                    || binding.binding_revision == 0
                    || binding.binding_revision >= SAFE_INTEGER
                    || binding.package_id != metadata.slot.package_id
                    || binding.sha256 != metadata.slot.sha256
                    || !wire::hex(&binding.history_scope_fingerprint)
                    || binding.source_ids.len() > 200
                    || binding.source_ids.windows(2).any(|ids| ids[0] >= ids[1])
            })
        {
            return Err("OFFLINE_PACK_CORRUPT");
        }
        Ok(metadata)
    }
    fn metadata_aad(&self, id: &str, generation: u64) -> String {
        format!("offline-v1:{}:metadata:{id}:{generation}", self.namespace)
    }
    fn package_aad(&self, id: &str, generation: u64, epoch: u64) -> String {
        format!(
            "offline-v1:{}:package:{id}:{generation}:{epoch}",
            self.namespace
        )
    }
    fn public_slot(metadata: &Metadata, epoch: u64) -> Slot {
        let mut slot = metadata.slot.clone();
        slot.previous_owner = metadata.installed_epoch != epoch;
        slot.locked = slot.previous_owner && metadata.unlocked_epoch != Some(epoch);
        slot
    }
    fn active(
        &self,
        connection: &Connection,
        key: &[u8; 32],
    ) -> NativeResult<Vec<(Row, Metadata)>> {
        let mut statement=db(connection.prepare("SELECT id,generation,file_id,metadata FROM slots WHERE file_id IS NOT NULL ORDER BY id"))?;
        let rows = db(statement.query_map([], |row| {
            Ok(Row {
                id: row.get(0)?,
                generation: row.get::<_, i64>(1)? as u64,
                file_id: row.get(2)?,
                metadata: row.get(3)?,
            })
        }))?;
        let mut active = Vec::new();
        for row in rows {
            let row = db(row)?;
            let metadata = self.metadata(&row, key)?;
            active.push((row, metadata));
            if active.len() > MAX_SLOTS {
                return Err("OFFLINE_PACK_CORRUPT");
            }
        }
        Ok(active)
    }
    pub fn list(&self) -> NativeResult<List> {
        let inner = self.lock()?;
        let vault = self.vault(&inner.connection, &inner.key)?;
        let items = self
            .active(&inner.connection, &inner.key)?
            .iter()
            .map(|(_, metadata)| Self::public_slot(metadata, vault.owner_epoch))
            .collect();
        Ok(List {
            schema: "offline-host@1",
            data_state: "local_snapshot",
            profile_id: vault.profile_id,
            owner_epoch: vault.owner_epoch,
            items,
        })
    }
    pub fn status(&self) -> Status {
        match self.list() {
            Ok(list) => Status::new(
                Some(list.profile_id),
                list.owner_epoch,
                list.items.iter().map(|slot| slot.byte_count).sum(),
                None,
            ),
            Err(error) => Status::unavailable(error),
        }
    }
    fn profile_lock(&self) -> NativeResult<File> {
        let lock = io(OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(self.root.join("install.lock")))?;
        lock.try_lock().map_err(|_| "OFFLINE_INSTALL_BUSY")?;
        Ok(lock)
    }
    fn fallback_profile_lock(&self) -> NativeResult<File> {
        // Separate from the long-lived download staging lock: a reset may still
        // invalidate an outstanding install ticket before its publication.
        let lock = io(OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(self.root.join("fallback.lock")))?;
        lock.try_lock().map_err(|_| "OFFLINE_INSTALL_BUSY")?;
        Ok(lock)
    }
    pub fn begin_install(&self, request: &InstallRequest) -> NativeResult<InstallTicket> {
        request.validate()?;
        let lock = self.profile_lock()?;
        let inner = self.lock()?;
        let vault = self.vault(&inner.connection, &inner.key)?;
        self.check_capacity(&inner.connection, &inner.key, request, vault.owner_epoch)?;
        // Only unreferenced immutable ciphertexts are removed, under the global
        // installation lock; active or reader-visible generations remain intact.
        let active = self.active(&inner.connection, &inner.key)?;
        let files = active
            .iter()
            .filter_map(|(row, _)| row.file_id.as_deref())
            .collect::<std::collections::HashSet<_>>();
        for entry in io(fs::read_dir(&self.root))? {
            let entry = io(entry)?;
            let path = entry.path();
            if path
                .extension()
                .is_some_and(|extension| extension == "pack")
                && path
                    .file_stem()
                    .and_then(|id| id.to_str())
                    .is_some_and(|id| wire::uuid(id) && !files.contains(id))
            {
                io(fs::remove_file(path))?;
            }
        }
        Ok(InstallTicket {
            _lock: lock,
            owner_epoch: vault.owner_epoch,
        })
    }
    fn check_capacity(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        request: &InstallRequest,
        epoch: u64,
    ) -> NativeResult<u64> {
        let row = Self::row(connection, &request.slot_id)?;
        let current = row.as_ref().map(|row| row.generation).unwrap_or(0);
        let is_active = row.as_ref().is_some_and(|row| row.file_id.is_some());
        if current != request.expected_generation {
            return Err("OFFLINE_GENERATION_CONFLICT");
        }
        if let Some(row) = row.as_ref().filter(|row| row.file_id.is_some()) {
            if Self::public_slot(&self.metadata(row, key)?, epoch).locked {
                return Err("OFFLINE_PREVIOUS_OWNER_LOCKED");
            }
        }
        let active = self.active(connection, key)?;
        let total = active
            .iter()
            .filter(|(row, _)| row.id != request.slot_id)
            .map(|(_, metadata)| metadata.slot.byte_count)
            .sum::<u64>();
        if total + request.expected_byte_count > MAX_STORE_BYTES
            || (!is_active && active.len() >= MAX_SLOTS)
        {
            return Err("OFFLINE_STORE_FULL");
        }
        row.map(|row| row.generation)
            .unwrap_or(0)
            .checked_add(1)
            .filter(|generation| *generation < SAFE_INTEGER)
            .ok_or("OFFLINE_GENERATION_EXHAUSTED")
    }
    pub fn install(
        &self,
        request: &InstallRequest,
        descriptor: Descriptor,
        bytes: Zeroizing<Vec<u8>>,
        ticket: InstallTicket,
    ) -> NativeResult<Slot> {
        let staged = self.stage_install(request, descriptor, bytes, ticket)?;
        self.publish_install(staged)
    }
    pub fn stage_install(
        &self,
        request: &InstallRequest,
        descriptor: Descriptor,
        bytes: Zeroizing<Vec<u8>>,
        ticket: InstallTicket,
    ) -> NativeResult<StagedInstall> {
        request.validate()?;
        let descriptor = wire::descriptor(
            &serde_json::to_vec(&descriptor).map_err(|_| "OFFLINE_PACK_INVALID")?,
            request,
        )?;
        let envelope = wire::package(&bytes, &descriptor)?;
        let key = {
            let inner = self.lock()?;
            Zeroizing::new(*inner.key)
        };
        let epoch = ticket.owner_epoch;
        let generation = request
            .expected_generation
            .checked_add(1)
            .filter(|g| *g < SAFE_INTEGER)
            .ok_or("OFFLINE_GENERATION_EXHAUSTED")?;
        let slot = Slot {
            slot_id: request.slot_id.clone(),
            generation,
            package_id: descriptor.id.clone(),
            sha256: descriptor.sha256.clone(),
            byte_count: descriptor.byte_count,
            title: format!("离线快照 · {}", descriptor.content_created_at),
            created_at: descriptor.content_created_at.clone(),
            installed_at: chrono::Utc::now().to_rfc3339(),
            privacy_class: descriptor.privacy_class.clone(),
            owner_scope_id: descriptor.owner_scope_id.clone(),
            locked: false,
            previous_owner: false,
            counts: descriptor.counts.clone(),
        };
        let metadata = Metadata {
            slot: slot.clone(),
            descriptor,
            installed_epoch: epoch,
            unlocked_epoch: None,
            fallback_binding: Some(Self::approved_fallback_binding(&slot, &envelope, &bytes)?),
        };
        let mut staged_index = Index::new(request.slot_id.clone(), generation, epoch, envelope)?;
        staged_index.original = Some(super::raw::Exact::parse(
            std::str::from_utf8(&bytes).map_err(|_| "OFFLINE_PACK_INVALID")?,
        )?);
        let sealed = crypto::seal(
            &key,
            self.package_aad(&request.slot_id, generation, epoch)
                .as_bytes(),
            &bytes,
        )?;
        let file_id = uuid::Uuid::new_v4().to_string();
        let path = self.root.join(format!("{file_id}.pack"));
        let mut file = io(OpenOptions::new().write(true).create_new(true).open(&path))?;
        if io(file.write_all(&sealed))
            .and_then(|()| io(file.sync_all()))
            .is_err()
        {
            drop(file);
            let _ = fs::remove_file(&path);
            return Err("OFFLINE_STORE_FAILED");
        }
        drop(file);
        let clear =
            Zeroizing::new(serde_json::to_vec(&metadata).map_err(|_| "OFFLINE_STORE_FAILED")?);
        let encoded = crypto::seal(
            &key,
            self.metadata_aad(&slot.slot_id, generation).as_bytes(),
            &clear,
        )?;
        Ok(StagedInstall {
            request: request.clone(),
            slot,
            file_id,
            encoded,
            index: Some(staged_index),
            path,
            published: false,
            _ticket: ticket,
        })
    }
    fn write_staged(
        &self,
        connection: &Connection,
        key: &[u8; 32],
        staged: &StagedInstall,
    ) -> NativeResult<()> {
        let vault = self.vault(connection, key)?;
        if vault.owner_epoch != staged._ticket.owner_epoch {
            return Err("OFFLINE_OWNER_CHANGED");
        }
        if self.check_capacity(connection, key, &staged.request, vault.owner_epoch)?
            != staged.slot.generation
        {
            return Err("OFFLINE_GENERATION_CONFLICT");
        }
        db(connection.execute("INSERT INTO slots(id,generation,file_id,metadata) VALUES(?1,?2,?3,?4) ON CONFLICT(id) DO UPDATE SET generation=excluded.generation,file_id=excluded.file_id,metadata=excluded.metadata",
            params![staged.slot.slot_id, staged.slot.generation as i64, staged.file_id, staged.encoded]))?;
        Ok(())
    }
    fn publish_install(&self, mut staged: StagedInstall) -> NativeResult<Slot> {
        let _profile = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let Inner {
            connection,
            key,
            index,
            fallback,
            ..
        } = &mut *inner;
        let tx = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        self.write_staged(&tx, key, &staged)?;
        self.sync_invalidate_slot(&tx, key, Some(&staged.slot.slot_id))?;
        self.sync_record_install(&tx, key, &staged.slot)?;
        self.fallback_invalidate_slot(&tx, key, Some(&staged.slot.slot_id), None)?;
        db(tx.commit())?;
        Self::fallback_cancel_pending(fallback);
        staged.published = true;
        *index = staged.index.take();
        Ok(staged.slot.clone())
    }
    fn load_index<'a>(
        &self,
        inner: &'a mut Inner,
        request: &SlotRequest,
    ) -> NativeResult<(Slot, &'a Index)> {
        request.validate()?;
        let vault = self.vault(&inner.connection, &inner.key)?;
        let row = Self::row(&inner.connection, &request.slot_id)?
            .filter(|row| row.file_id.is_some())
            .ok_or("OFFLINE_SLOT_NOT_FOUND")?;
        if row.generation != request.expected_generation {
            return Err("OFFLINE_GENERATION_CONFLICT");
        }
        let metadata = self.metadata(&row, &inner.key)?;
        let slot = Self::public_slot(&metadata, vault.owner_epoch);
        self.release_gate(&inner.connection, &inner.key, &slot)?;
        if slot.locked {
            inner.index = None;
            return Err("OFFLINE_PREVIOUS_OWNER_LOCKED");
        }
        if !inner.index.as_ref().is_some_and(|index| {
            index.slot_id == row.id
                && index.generation == row.generation
                && index.owner_epoch == vault.owner_epoch
        }) {
            inner.index = None;
            let path = self.root.join(format!(
                "{}.pack",
                row.file_id.as_deref().ok_or("OFFLINE_PACK_CORRUPT")?
            ));
            let file_metadata = io(fs::symlink_metadata(&path))?;
            if !file_metadata.is_file()
                || file_metadata.file_type().is_symlink()
                || file_metadata.len() > (MAX_PACKAGE_BYTES + crypto::OVERHEAD) as u64
            {
                return Err("OFFLINE_PACK_CORRUPT");
            }
            let mut encoded = Vec::new();
            io(File::open(path))?
                .take((MAX_PACKAGE_BYTES + crypto::OVERHEAD + 1) as u64)
                .read_to_end(&mut encoded)
                .map_err(|_| "OFFLINE_STORE_FAILED")?;
            let clear = crypto::open(
                &inner.key,
                self.package_aad(&row.id, row.generation, metadata.installed_epoch)
                    .as_bytes(),
                &encoded,
                MAX_PACKAGE_BYTES,
            )?;
            let envelope = wire::package(&clear, &metadata.descriptor)?;
            let mut index = Index::new(row.id, row.generation, vault.owner_epoch, envelope)?;
            index.original = Some(super::raw::Exact::parse(
                std::str::from_utf8(&clear).map_err(|_| "OFFLINE_PACK_INVALID")?,
            )?);
            inner.index = Some(index);
        }
        Ok((
            slot,
            inner.index.as_ref().ok_or("OFFLINE_INDEX_UNAVAILABLE")?,
        ))
    }
    pub fn search(&self, request: SearchRequest) -> NativeResult<SearchResult> {
        if request.query.len() > 2048
            || request.query.chars().count() > 512
            || request.query.contains('\0')
            || request.limit == 0
            || request.limit > 50
            || request.offset > 4_000
            || request.kind.as_deref().is_some_and(|kind| {
                !matches!(
                    kind,
                    "tire"
                        | "vehicle"
                        | "test_event"
                        | "recall"
                        | "recall_search"
                        | "garage"
                        | "watchlist"
                )
            })
        {
            return Err("OFFLINE_INVALID_ARGUMENT");
        }
        let mut inner = self.lock()?;
        let (slot, index) = self.load_index(
            &mut inner,
            &SlotRequest {
                slot_id: request.slot_id,
                expected_generation: request.expected_generation,
            },
        )?;
        let (items, total) = index.search(
            &request.query,
            request.kind.as_deref(),
            request.limit,
            request.offset,
        )?;
        Ok(SearchResult {
            data_state: "local_snapshot",
            slot,
            items,
            total,
            offset: request.offset,
            limit: request.limit,
            has_more: request.offset + request.limit < total,
        })
    }
    pub fn read(&self, request: ReadRequest) -> NativeResult<ReadResult> {
        if request.document_id.is_empty() || request.document_id.len() > 256 {
            return Err("OFFLINE_INVALID_ARGUMENT");
        }
        let mut inner = self.lock()?;
        let (slot, index) = self.load_index(
            &mut inner,
            &SlotRequest {
                slot_id: request.slot_id,
                expected_generation: request.expected_generation,
            },
        )?;
        let document = index
            .envelope
            .documents
            .iter()
            .find(|doc| doc.id == request.document_id)
            .ok_or("OFFLINE_DOCUMENT_NOT_FOUND")?
            .clone();
        let member = document
            .member_key
            .as_ref()
            .and_then(|key| {
                index
                    .envelope
                    .members
                    .iter()
                    .find(|member| &member.key == key)
            })
            .cloned();
        let context = document
            .context_id
            .as_ref()
            .and_then(|id| {
                index
                    .envelope
                    .contexts
                    .iter()
                    .find(|context| &context.id == id)
            })
            .cloned();
        Ok(ReadResult {
            data_state: "local_snapshot",
            slot,
            document,
            member,
            context,
        })
    }
    pub fn read_wire(&self, request: ReadRequest) -> NativeResult<serde_json::Value> {
        if request.document_id.is_empty() || request.document_id.len() > 256 {
            return Err("OFFLINE_INVALID_ARGUMENT");
        }
        let mut inner = self.lock()?;
        let (slot, index) = self.load_index(
            &mut inner,
            &SlotRequest {
                slot_id: request.slot_id,
                expected_generation: request.expected_generation,
            },
        )?;
        let document = index
            .envelope
            .documents
            .iter()
            .find(|d| d.id == request.document_id)
            .ok_or("OFFLINE_DOCUMENT_NOT_FOUND")?
            .clone();
        if index.envelope.schema == "offline-pack@1" {
            let member = document
                .member_key
                .as_ref()
                .and_then(|key| index.envelope.members.iter().find(|m| &m.key == key))
                .cloned();
            let context = document
                .context_id
                .as_ref()
                .and_then(|id| index.envelope.contexts.iter().find(|c| &c.id == id))
                .cloned();
            return serde_json::to_value(ReadResult {
                data_state: "local_snapshot",
                slot,
                document,
                member,
                context,
            })
            .map_err(|_| "OFFLINE_PACK_INVALID");
        }
        if index.envelope.schema != "offline-pack@2" {
            return Err("OFFLINE_PACK_INVALID");
        }
        use super::raw::Exact;
        let original = index.original.as_ref().ok_or("OFFLINE_PACK_CORRUPT")?;
        let member = original
            .get("members")
            .ok_or("OFFLINE_PACK_CORRUPT")?
            .array()?
            .iter()
            .find(|m| m.get("key").and_then(|k| k.text().ok()) == document.member_key.as_deref())
            .cloned()
            .unwrap_or(Exact::Null);
        let context = original
            .get("contexts")
            .ok_or("OFFLINE_PACK_CORRUPT")?
            .array()?
            .iter()
            .find(|c| c.get("id").and_then(|id| id.text().ok()) == document.context_id.as_deref())
            .cloned()
            .unwrap_or(Exact::Null);
        let mut core=Exact::parse(&serde_json::to_string(&serde_json::json!({"schema":"offline-read-result@2","package_schema":"offline-pack@2","data_state":"local_snapshot","slot":slot,"document":document,"member":null,"context":null})).map_err(|_|"OFFLINE_PACK_INVALID")?)?;
        if let Exact::Object(fields) = &mut core {
            fields.insert("member".into(), member);
            fields.insert("context".into(), context);
        }
        super::raw::encode_transport(&core)
    }
    pub fn remove(&self, request: SlotRequest) -> NativeResult<RemoveResult> {
        request.validate()?;
        let _profile_lock = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let Inner {
            connection,
            key,
            index,
            fallback,
            ..
        } = &mut *inner;
        let transaction = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let row = Self::row(&transaction, &request.slot_id)?
            .filter(|row| row.file_id.is_some())
            .ok_or("OFFLINE_SLOT_NOT_FOUND")?;
        if row.generation != request.expected_generation {
            return Err("OFFLINE_GENERATION_CONFLICT");
        }
        let generation = row
            .generation
            .checked_add(1)
            .filter(|generation| *generation < SAFE_INTEGER)
            .ok_or("OFFLINE_GENERATION_EXHAUSTED")?;
        db(transaction.execute(
            "UPDATE slots SET generation=?1,file_id=NULL,metadata=NULL WHERE id=?2",
            params![generation as i64, request.slot_id],
        ))?;
        self.sync_invalidate_slot(&transaction, key, Some(&request.slot_id))?;
        self.fallback_invalidate_slot(&transaction, key, Some(&request.slot_id), None)?;
        db(transaction.commit())?;
        Self::fallback_cancel_pending(fallback);
        *index = None;
        if let Some(file_id) = row.file_id.filter(|id| wire::uuid(id)) {
            let _ = fs::remove_file(self.root.join(format!("{file_id}.pack")));
        }
        Ok(RemoveResult {
            removed: true,
            slot_id: request.slot_id,
            generation,
        })
    }
    pub fn unlock(&self, request: UnlockRequest) -> NativeResult<Slot> {
        if !request.allow_previous_owner {
            return Err("OFFLINE_PREVIOUS_OWNER_CONSENT_REQUIRED");
        }
        let slot_request = SlotRequest {
            slot_id: request.slot_id.clone(),
            expected_generation: request.expected_generation,
        };
        slot_request.validate()?;
        let _profile_lock = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let Inner {
            connection,
            key,
            index,
            ..
        } = &mut *inner;
        let transaction = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let vault = self.vault(&transaction, key)?;
        let row = Self::row(&transaction, &request.slot_id)?
            .filter(|row| row.file_id.is_some())
            .ok_or("OFFLINE_SLOT_NOT_FOUND")?;
        if row.generation != request.expected_generation {
            return Err("OFFLINE_GENERATION_CONFLICT");
        }
        let mut metadata = self.metadata(&row, key)?;
        metadata.unlocked_epoch = Some(vault.owner_epoch);
        let clear =
            Zeroizing::new(serde_json::to_vec(&metadata).map_err(|_| "OFFLINE_STORE_FAILED")?);
        let sealed = crypto::seal(
            key,
            self.metadata_aad(&row.id, row.generation).as_bytes(),
            &clear,
        )?;
        db(transaction.execute(
            "UPDATE slots SET metadata=?1 WHERE id=?2",
            params![sealed, row.id],
        ))?;
        db(transaction.commit())?;
        *index = None;
        Ok(Self::public_slot(&metadata, vault.owner_epoch))
    }
    pub fn reset_owner(&self) -> NativeResult<()> {
        let _profile_lock = self.fallback_profile_lock()?;
        let mut inner = self.lock()?;
        let Inner {
            connection,
            key,
            index,
            fallback,
            ..
        } = &mut *inner;
        let transaction = db(connection.transaction_with_behavior(TransactionBehavior::Immediate))?;
        let mut vault = self.vault(&transaction, key)?;
        vault.owner_epoch = vault
            .owner_epoch
            .checked_add(1)
            .filter(|epoch| *epoch < SAFE_INTEGER)
            .ok_or("OFFLINE_GENERATION_EXHAUSTED")?;
        let clear = Zeroizing::new(serde_json::to_vec(&vault).map_err(|_| "OFFLINE_STORE_FAILED")?);
        let sealed = crypto::seal(
            key,
            format!("offline-v1:{}:state", self.namespace).as_bytes(),
            &clear,
        )?;
        db(transaction.execute("UPDATE vault SET value=?1 WHERE id=1", [sealed]))?;
        self.sync_invalidate_slot(&transaction, key, None)?;
        self.fallback_reset_owner_control(&transaction, key, &vault.profile_id, vault.owner_epoch)?;
        db(transaction.commit())?;
        *index = None;
        Self::fallback_reset_runtime(fallback);
        inner.sync.clear();
        Ok(())
    }
}
