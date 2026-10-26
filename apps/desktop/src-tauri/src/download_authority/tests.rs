use super::*;
use std::sync::{atomic::{AtomicU64, AtomicUsize, Ordering}, Barrier};

#[test]
fn opaque_single_use_document_release_expiry_and_capacity() {
    let now = Arc::new(AtomicU64::new(0)); let clock = now.clone();
    let authority = DownloadAuthority::with_clock(Arc::new(move || Duration::from_nanos(clock.load(Ordering::SeqCst))));
    let document = authority.document().unwrap(); let other = authority.document().unwrap();
    let token = authority.prepare(&document).unwrap();
    assert_eq!(token.len(), 64); assert_ne!(token, authority.prepare(&document).unwrap());
    assert!(authority.reserve("forged", &document).is_err());
    assert!(authority.reserve(&token, &other).is_err());
    authority.release(&token, &other);
    let reservation = authority.reserve(&token, &document).unwrap();
    assert!(authority.reserve(&token, &document).is_err());
    reservation.commit().unwrap(); assert!(reservation.commit().is_err());
    authority.release(&token, &document); authority.invalidate().unwrap();
    // Committing authorization survives release/invalidation; it is never issued twice.
    assert!(matches!(authority.gate.lock().unwrap().leases[&token].phase, Phase::Committing));
    drop(reservation); assert!(!authority.gate.lock().unwrap().leases.contains_key(&token));
    let token = authority.prepare(&document).unwrap();
    authority.release(&token, &document); authority.release(&token, &document);
    assert!(authority.reserve(&token, &document).is_err());
    let token = authority.prepare(&document).unwrap();
    let reservation = authority.reserve(&token, &document).unwrap();
    now.store(TTL.as_nanos() as u64, Ordering::SeqCst);
    assert!(reservation.commit().is_err()); drop(reservation);
    for _ in 0..MAX_LEASES { authority.prepare(&document).unwrap(); }
    assert_eq!(authority.prepare(&document).err(), Some("DOWNLOAD_DIALOG_BUSY"));
    now.store((TTL.as_nanos() * 2) as u64, Ordering::SeqCst);
    authority.prepare(&document).unwrap();
    let other_lease = authority.prepare(&other).unwrap();
    authority.end_document(&document);
    assert!(authority.prepare(&document).is_err());
    authority.reserve(&other_lease, &other).unwrap().commit().unwrap();
    authority.close(); assert!(authority.prepare(&other).is_err());
}

#[test]
fn identity_pending_is_ticket_scoped_and_end_revokes_again_without_cookie_comparison() {
    let authority = DownloadAuthority::new(); let document = authority.document().unwrap();
    let old = authority.prepare(&document).unwrap();
    let first = authority.begin_transition().unwrap();
    assert!(authority.prepare(&document).is_err()); assert!(authority.reserve(&old, &document).is_err());
    let second = authority.begin_transition().unwrap(); drop(first);
    assert!(authority.prepare(&document).is_err());
    let revision = authority.gate.lock().unwrap().revision;
    drop(second); assert!(authority.gate.lock().unwrap().revision > revision);
    assert!(authority.reserve(&old, &document).is_err());
    let between = authority.prepare(&document).unwrap();
    // Login/logout/me failure with an unchanged cookie still performs both transitions.
    for _ in ["login same cookie", "logout same cookie", "GET me failed", "reset", "recover", "config"] {
        let transition = authority.begin_transition().unwrap();
        assert!(authority.prepare(&document).is_err()); drop(transition);
    }
    assert!(authority.reserve(&between, &document).is_err());
    let token = authority.prepare(&document).unwrap(); let reservation = authority.reserve(&token, &document).unwrap();
    let pending = authority.begin_transition().unwrap(); assert!(reservation.commit().is_err()); drop(pending);
    assert!(reservation.commit().is_err());
    authority.gate.lock().unwrap().revision = u64::MAX;
    assert!(authority.begin_transition().is_err()); assert!(authority.prepare(&document).is_err());
}

#[test]
fn normalized_identity_routes_cover_encoded_auth_queries_and_user_mutations() {
    for (method, route) in [
        ("GET", "/v1/auth/me"), ("GET", "/v1/auth/%6de?mode=history&x=%E8%AF%81"),
        ("POST", "/v1/%61uth/%6cogin?x=1"), ("POST", "/v1/auth/logout"), ("POST", "/v1/auth/register"),
        ("POST", "/v1/auth/profile"), ("POST", "/v1/auth/users/a/role"), ("POST", "/v1/auth/users/a/password"),
        ("DELETE", "/v1/auth/users/a?mode=history")
    ] { assert!(identity_request(method, route).unwrap(), "{method} {route}"); }
    for (method, route) in [("POST", "/v1/auth/me"), ("GET", "/v1/auth/login"), ("GET", "/v1/vehicle-queries"),
        ("POST", "/v1/auth/login/"), ("POST", "/v1/auth/users/a/role/extra"), ("DELETE", "/v1/auth/users/")] {
        assert!(!identity_request(method, route).unwrap(), "{method} {route}");
    }
    for route in ["/v1/%2561uth/login", "/v1/auth%2flogin", "/v1/auth/%ff", "/v1/auth/%", "/v1/auth/%0G", "/v1/auth/%2e%2e/login"] {
        assert!(identity_request("POST", route).is_err(), "{route}");
    }
}

#[test]
fn revocation_before_commit_has_zero_open_write_and_commit_winner_is_not_rollback() {
    for commit_first in [false, true] {
        let authority = DownloadAuthority::new(); let document = authority.document().unwrap();
        let lease = authority.prepare(&document).unwrap(); let reservation = authority.reserve(&lease, &document).unwrap();
        let ready = Arc::new(Barrier::new(2)); let proceed = Arc::new(Barrier::new(2));
        let opened = Arc::new(AtomicUsize::new(0)); let written = Arc::new(AtomicUsize::new(0));
        let (r, p, o, w) = (ready.clone(), proceed.clone(), opened.clone(), written.clone());
        let worker = std::thread::spawn(move || {
            if commit_first { reservation.commit().unwrap(); }
            r.wait(); p.wait();
            if !commit_first && reservation.commit().is_err() { return; }
            // The gate is released before this actual destination open/write.
            o.fetch_add(1, Ordering::SeqCst); w.fetch_add(7, Ordering::SeqCst);
        });
        ready.wait(); let transition = authority.begin_transition().unwrap(); authority.release(&lease, &document); proceed.wait();
        worker.join().unwrap(); drop(transition);
        assert_eq!(opened.load(Ordering::SeqCst), usize::from(commit_first));
        assert_eq!(written.load(Ordering::SeqCst), if commit_first { 7 } else { 0 });
    }
}
