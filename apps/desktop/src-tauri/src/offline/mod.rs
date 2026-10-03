//! Device-owned encrypted packages. Never a network/session fallback.
pub mod conditions;
pub(crate) mod criteria;
mod crypto;
mod index;
pub(crate) mod raw;
mod store;
pub mod sync;
pub mod wire;
pub use store::*;

#[cfg(test)]
pub(crate) mod tests;

pub const MAX_PACKAGE_BYTES: usize = 8 * 1024 * 1024;
pub const MAX_STORE_BYTES: u64 = 32 * 1024 * 1024;
pub const MAX_SLOTS: usize = 16;
