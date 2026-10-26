//! Independent account/document publication authority. The mutex never spans picker or file I/O.
use std::{collections::{HashMap, HashSet}, sync::{Arc, Mutex}, time::{Duration, Instant}};
use uuid::Uuid;

type Result<T> = std::result::Result<T, &'static str>;
const CHANGED: &str = "DOWNLOAD_CONTEXT_CHANGED";
const UNAVAILABLE: &str = "DOWNLOAD_AUTHORITY_UNAVAILABLE";
const MAX_LEASES: usize = 128;
const MAX_TRANSITIONS: usize = 128;
const TTL: Duration = Duration::from_secs(120);

fn opaque() -> String { format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple()) }
#[derive(Clone, Copy, PartialEq, Eq)]
enum Phase { Prepared, Reserved, Committing }
struct Lease { document: String, revision: u64, issued: Duration, phase: Phase }
#[derive(Default)]
struct Gate { revision: u64, closed: bool, documents: HashSet<String>, pending: HashSet<String>, leases: HashMap<String, Lease> }
pub struct DownloadAuthority { gate: Mutex<Gate>, clock: Arc<dyn Fn() -> Duration + Send + Sync> }

impl DownloadAuthority {
    pub fn new() -> Arc<Self> {
        let start = Instant::now();
        Self::with_clock(Arc::new(move || start.elapsed()))
    }
    fn with_clock(clock: Arc<dyn Fn() -> Duration + Send + Sync>) -> Arc<Self> {
        Arc::new(Self { gate: Mutex::new(Gate::default()), clock })
    }
    fn bump(gate: &mut Gate) -> Result<()> {
        gate.leases.retain(|_, lease| lease.phase == Phase::Committing);
        match gate.revision.checked_add(1) {
            Some(next) if !gate.closed => { gate.revision = next; Ok(()) }
            _ => { gate.closed = true; Err(UNAVAILABLE) }
        }
    }
    fn prune(&self, gate: &mut Gate) {
        let now = (self.clock)();
        gate.leases.retain(|_, lease| lease.phase == Phase::Committing || now.checked_sub(lease.issued).is_some_and(|age| age < TTL));
    }
    pub fn document(&self) -> Result<String> {
        let mut gate = self.gate.lock().map_err(|_| UNAVAILABLE)?;
        if gate.closed || gate.documents.len() >= 16 { return Err(UNAVAILABLE); }
        let token = opaque(); gate.documents.insert(token.clone()); Ok(token)
    }
    pub fn end_document(&self, document: &str) {
        if let Ok(mut gate) = self.gate.lock() {
            gate.documents.remove(document);
            gate.leases.retain(|_, lease| lease.document != document || lease.phase == Phase::Committing);
        }
    }
    pub fn invalidate(&self) -> Result<()> {
        let mut gate = self.gate.lock().map_err(|_| UNAVAILABLE)?;
        Self::bump(&mut gate)
    }
    pub fn close(&self) { if let Ok(mut gate) = self.gate.lock() { let _ = Self::bump(&mut gate); gate.closed = true; gate.documents.clear(); } }
    pub fn begin_transition(self: &Arc<Self>) -> Result<Transition> {
        let mut gate = self.gate.lock().map_err(|_| UNAVAILABLE)?;
        Self::bump(&mut gate)?;
        if gate.pending.len() >= MAX_TRANSITIONS { gate.closed = true; return Err(UNAVAILABLE); }
        let ticket = opaque(); gate.pending.insert(ticket.clone());
        Ok(Transition { authority: self.clone(), ticket })
    }
    pub fn prepare(&self, document: &str) -> Result<String> {
        let mut gate = self.gate.lock().map_err(|_| UNAVAILABLE)?; self.prune(&mut gate);
        if gate.closed || !gate.pending.is_empty() || !gate.documents.contains(document) { return Err(CHANGED); }
        if gate.leases.len() >= MAX_LEASES { return Err("DOWNLOAD_DIALOG_BUSY"); }
        let token = opaque(); let revision = gate.revision;
        gate.leases.insert(token.clone(), Lease { document: document.into(), revision, issued: (self.clock)(), phase: Phase::Prepared }); Ok(token)
    }
    fn advance(&self, token: &str, document: &str, from: Phase, to: Phase) -> Result<()> {
        let mut gate = self.gate.lock().map_err(|_| UNAVAILABLE)?; self.prune(&mut gate);
        if gate.closed || !gate.pending.is_empty() || !gate.documents.contains(document) { return Err(CHANGED); }
        let revision = gate.revision;
        let lease = gate.leases.get_mut(token).ok_or(CHANGED)?;
        if lease.document != document || lease.revision != revision || lease.phase != from { return Err(CHANGED); }
        lease.phase = to; Ok(())
    }
    pub fn reserve(self: &Arc<Self>, token: &str, document: &str) -> Result<Reservation> {
        self.advance(token, document, Phase::Prepared, Phase::Reserved)?;
        Ok(Reservation { authority: self.clone(), token: token.into(), document: document.into() })
    }
    pub fn release(&self, token: &str, document: &str) {
        if let Ok(mut gate) = self.gate.lock() {
            if gate.leases.get(token).is_some_and(|lease| lease.document == document && lease.phase != Phase::Committing) { gate.leases.remove(token); }
        }
    }
}
pub struct Transition { authority: Arc<DownloadAuthority>, ticket: String }
impl Drop for Transition {
    fn drop(&mut self) {
        if let Ok(mut gate) = self.authority.gate.lock() {
            // A concurrent/older request can only finish its own pending ticket.
            if gate.pending.remove(&self.ticket) { let _ = DownloadAuthority::bump(&mut gate); }
        }
    }
}
pub struct Reservation { authority: Arc<DownloadAuthority>, token: String, document: String }
impl Reservation {
    /// Linearization point. Once this succeeds, later revocation cannot promise rollback.
    pub fn commit(&self) -> Result<()> { self.authority.advance(&self.token, &self.document, Phase::Reserved, Phase::Committing) }
}
impl Drop for Reservation {
    fn drop(&mut self) { if let Ok(mut gate) = self.authority.gate.lock() { gate.leases.remove(&self.token); } }
}

/// Called only after existing request validation; preserve raw encoded network paths.
pub fn identity_request(method: &str, path: &str) -> Result<bool> {
    let raw = path.split('?').next().ok_or("INVALID_API_PATH")?;
    for (i, b) in raw.bytes().enumerate() {
        if b == b'%' && (i + 2 >= raw.len() || !raw.as_bytes()[i+1].is_ascii_hexdigit() || !raw.as_bytes()[i+2].is_ascii_hexdigit()) { return Err("INVALID_API_PATH"); }
    }
    let route = percent_encoding::percent_decode_str(raw).decode_utf8().map_err(|_| "INVALID_API_PATH")?;
    if route.contains(['%', '\\', '#', '?']) || route.chars().any(char::is_control)
        || route.bytes().filter(|b| *b == b'/').count() != raw.bytes().filter(|b| *b == b'/').count()
        || route.split('/').any(|part| part == "." || part == "..") { return Err("INVALID_API_PATH"); }
    let parts: Vec<_> = route.split('/').collect();
    Ok((method == "GET" && route == "/v1/auth/me")
        || (method == "POST" && matches!(route.as_ref(), "/v1/auth/register" | "/v1/auth/login" | "/v1/auth/logout" | "/v1/auth/profile"))
        || (parts.len() >= 5 && parts[..4] == ["", "v1", "auth", "users"] && !parts[4].is_empty()
            && ((method == "DELETE" && parts.len() == 5) || (method == "POST" && parts.len() == 6 && matches!(parts[5], "role" | "password")))))
}

#[cfg(test)]
#[path = "download_authority/tests.rs"]
mod tests;
