//! Derived search state is memory-only and is never the authority for details.
use super::wire::{Document, Envelope};
use crate::security::NativeResult;
use rusqlite::{params, Connection};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

pub struct Index {
    pub slot_id: String,
    pub generation: u64,
    pub owner_epoch: u64,
    pub envelope: Envelope,
    pub(crate) original: Option<super::raw::Exact>,
    connection: Connection,
}

// unicode61 alone treats a whole Chinese sentence as a token. Index Han and
// other non-ASCII characters individually so even one-character queries work.
// Every query token is quoted; FTS operators are never accepted from IPC.
fn terms(value: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut ascii = String::new();
    for character in value.chars() {
        if character.is_ascii_alphanumeric() {
            ascii.push(character.to_ascii_lowercase());
        } else {
            if !ascii.is_empty() {
                out.push(std::mem::take(&mut ascii));
            }
            if character.is_alphanumeric() {
                out.push(character.to_string().to_lowercase());
            }
        }
    }
    if !ascii.is_empty() {
        out.push(ascii);
    }
    out
}

fn query_expression(value: &str) -> NativeResult<String> {
    let mut groups = Vec::new();
    let mut current = String::new();
    let mut ascii = None;
    for character in value.chars().chain(std::iter::once(' ')) {
        let next = character.is_alphanumeric().then_some(character.is_ascii());
        if next != ascii || next.is_none() {
            if !current.is_empty() {
                groups.push(format!("\"{}\"", terms(&current).join(" ")));
                current.clear();
            }
            ascii = next;
        }
        if next.is_some() {
            current.push(character);
        }
    }
    if groups.len() > 128 {
        return Err("OFFLINE_INVALID_ARGUMENT");
    }
    Ok(groups.join(" AND "))
}

impl Index {
    pub fn new(
        slot_id: String,
        generation: u64,
        owner_epoch: u64,
        envelope: Envelope,
    ) -> NativeResult<Self> {
        let mut connection =
            Connection::open_in_memory().map_err(|_| "OFFLINE_INDEX_UNAVAILABLE")?;
        connection.execute_batch("PRAGMA temp_store=MEMORY; PRAGMA cache_size=-8192; CREATE VIRTUAL TABLE search USING fts5(title,text,brand,model,size,source,campaign,kind UNINDEXED, tokenize='unicode61');")
            .map_err(|_| "OFFLINE_INDEX_UNAVAILABLE")?;
        connection
            .set_limit(
                rusqlite::limits::Limit::SQLITE_LIMIT_LENGTH,
                // Derived Unicode tokens add separators and may expand during
                // case folding; original transport remains strictly 8 MiB.
                16 * 1024 * 1024,
            )
            .map_err(|_| "OFFLINE_INDEX_UNAVAILABLE")?;
        connection
            .set_limit(rusqlite::limits::Limit::SQLITE_LIMIT_SQL_LENGTH, 32 * 1024)
            .map_err(|_| "OFFLINE_INDEX_UNAVAILABLE")?;
        let transaction = connection
            .transaction()
            .map_err(|_| "OFFLINE_INDEX_UNAVAILABLE")?;
        {
            let mut insert = transaction.prepare("INSERT INTO search(rowid,title,text,brand,model,size,source,campaign,kind) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9)").map_err(|_| "OFFLINE_INDEX_UNAVAILABLE")?;
            for (index, document) in envelope.documents.iter().enumerate() {
                let facets = &document.facets;
                let values = [
                    document.title.as_str(),
                    document.text.as_str(),
                    facets.brand.as_deref().unwrap_or(""),
                    facets.model.as_deref().unwrap_or(""),
                    facets.size.as_deref().unwrap_or(""),
                    facets.source_id.as_deref().unwrap_or(""),
                    facets.campaign_number.as_deref().unwrap_or(""),
                ];
                let text = values.map(|value| terms(value).join(" "));
                insert
                    .execute(params![
                        index as i64 + 1,
                        text[0],
                        text[1],
                        text[2],
                        text[3],
                        text[4],
                        text[5],
                        text[6],
                        document.kind
                    ])
                    .map_err(|_| "OFFLINE_INDEX_UNAVAILABLE")?;
            }
        }
        transaction
            .commit()
            .map_err(|_| "OFFLINE_INDEX_UNAVAILABLE")?;
        Ok(Self {
            slot_id,
            generation,
            owner_epoch,
            envelope,
            original: None,
            connection,
        })
    }

    pub fn search(
        &self,
        query: &str,
        kind: Option<&str>,
        limit: u64,
        offset: u64,
    ) -> NativeResult<(Vec<Document>, u64)> {
        let expression = query_expression(query)?;
        let literal_groups = query
            .split(|character: char| character.is_ascii() || !character.is_alphanumeric())
            .filter(|group| !group.is_empty())
            .map(str::to_lowercase)
            .collect::<Vec<_>>();
        // Punctuation-only input is not silently turned into browse-all.
        if expression.is_empty() && !query.trim().is_empty() {
            return Ok((Vec::new(), 0));
        }
        let budget = Arc::new(AtomicUsize::new(0));
        self.connection
            .progress_handler(
                1000,
                Some(move || budget.fetch_add(1, Ordering::Relaxed) >= 10_000),
            )
            .map_err(|_| "OFFLINE_INDEX_UNAVAILABLE")?;
        let result = (|| {
            let sql = if expression.is_empty() {
                "SELECT rowid FROM search WHERE (?2 IS NULL OR kind=?2) ORDER BY rowid LIMIT 4000"
            } else {
                "SELECT rowid FROM search WHERE search MATCH ?1 AND (?2 IS NULL OR kind=?2) ORDER BY bm25(search),rowid LIMIT 4000"
            };
            let mut statement = self
                .connection
                .prepare(sql)
                .map_err(|_| "OFFLINE_SEARCH_FAILED")?;
            let ids = statement
                .query_map(params![expression, kind], |row| row.get::<_, i64>(0))
                .map_err(|_| "OFFLINE_SEARCH_FAILED")?;
            let mut documents = Vec::new();
            let mut total = 0;
            for id in ids {
                let id = id.map_err(|_| "OFFLINE_SEARCH_FAILED")? as usize;
                let document = self
                    .envelope
                    .documents
                    .get(id.wrapping_sub(1))
                    .ok_or("OFFLINE_INDEX_UNAVAILABLE")?;
                // FTS is the candidate source. Confirm literal non-ASCII runs
                // on these derived fields, because unicode61 drops punctuation
                // and a phrase alone would incorrectly match e.g. 上，海.
                if !literal_groups.is_empty() {
                    let facets = &document.facets;
                    let values = [
                        document.title.as_str(),
                        document.text.as_str(),
                        facets.brand.as_deref().unwrap_or(""),
                        facets.model.as_deref().unwrap_or(""),
                        facets.size.as_deref().unwrap_or(""),
                        facets.source_id.as_deref().unwrap_or(""),
                        facets.campaign_number.as_deref().unwrap_or(""),
                    ]
                    .map(str::to_lowercase);
                    if !literal_groups
                        .iter()
                        .all(|group| values.iter().any(|value| value.contains(group)))
                    {
                        continue;
                    }
                }
                if total >= offset && total < offset + limit {
                    documents.push(document.clone());
                }
                total += 1;
            }
            Ok((documents, total))
        })();
        self.connection
            .progress_handler(0, None::<fn() -> bool>)
            .map_err(|_| "OFFLINE_INDEX_UNAVAILABLE")?;
        result
    }
}
