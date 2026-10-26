package org.taiji.tireintelligence.mobile;

import java.lang.reflect.Field;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/** Exercises the actual application authority; no cookie-derived substitute authority. */
public final class DownloadAuthorityTest {
    private static int checks;
    private interface Action { void run() throws Exception; }
    private static void check(boolean value, String label) { checks++; if (!value) throw new AssertionError(label); }
    private static void denied(Action action, String label) throws Exception {
        try { action.run(); throw new AssertionError(label); }
        catch (NativeFailure expected) { check(expected.code.equals("DOWNLOAD_CONTEXT_CHANGED") || expected.code.equals("DOWNLOAD_AUTHORITY_UNAVAILABLE") || expected.code.equals("DOWNLOAD_DIALOG_BUSY"), label); }
    }
    public static void main(String[] arguments) throws Exception {
        AtomicLong clock = new AtomicLong(); DownloadAuthority authority = new DownloadAuthority(clock::get);
        String document = authority.document(), other = authority.document(), token = authority.prepare(document);
        check(token.matches("[0-9a-f]{64}") && !token.equals(authority.prepare(document)), "opaque unpredictable unique leases");
        denied(() -> authority.reserve("forged", document), "forged token denied");
        denied(() -> authority.reserve(token, other), "other document cannot reserve");
        check(!authority.release(token, other), "other document cannot release");
        DownloadAuthority.Reservation reservation = authority.reserve(token, document);
        denied(() -> authority.reserve(token, document), "double reserve denied");
        reservation.commit(); denied(reservation::commit, "double commit denied");
        check(!authority.release(token, document), "release after commit cannot revoke its authorization");
        authority.invalidate(); reservation.close();
        denied(() -> authority.reserve(token, document), "finished single-use lease stays dead");
        String released = authority.prepare(document);
        check(authority.release(released, document) && !authority.release(released, document), "release is idempotent");
        denied(() -> authority.reserve(released, document), "released lease cannot reserve");
        String expired = authority.prepare(document); DownloadAuthority.Reservation timed = authority.reserve(expired, document);
        clock.set(120_000_000_000L); denied(timed::commit, "TTL expires a picker reservation"); timed.close();
        for (int i = 0; i < 128; i++) authority.prepare(document);
        denied(() -> authority.prepare(document), "pending lease table bounded");
        clock.set(240_000_000_000L); authority.prepare(document);
        String sibling = authority.prepare(other); authority.endDocument(document);
        denied(() -> authority.prepare(document), "ended document cannot mint leases");
        try (DownloadAuthority.Reservation live = authority.reserve(sibling, other)) { live.commit(); }
        authority.close(); denied(() -> authority.prepare(other), "closed authority fails closed");

        DownloadAuthority accounts = new DownloadAuthority(); String page = accounts.document(), before = accounts.prepare(page);
        DownloadAuthority.Transition first = accounts.beginTransition(), second = accounts.beginTransition();
        denied(() -> accounts.prepare(page), "identity pending blocks prepare");
        denied(() -> accounts.reserve(before, page), "identity admitted before an old save arrives");
        first.close(); first.close(); denied(() -> accounts.prepare(page), "old finally only clears its own ticket");
        second.close(); String after = accounts.prepare(page);
        denied(() -> accounts.reserve(before, page), "request end never revives old authorization");
        try (DownloadAuthority.Reservation r = accounts.reserve(after, page)) {
            try (DownloadAuthority.Transition pending = accounts.beginTransition()) { denied(r::commit, "pending also blocks commit"); }
            denied(r::commit, "end invalidates again");
        }
        for (String mutation : List.of("same-cookie login", "same-cookie logout", "GET me failure", "profile", "role", "password", "delete", "reset", "recover", "config")) {
            String old = accounts.prepare(page);
            try (DownloadAuthority.Transition pending = accounts.beginTransition()) { denied(() -> accounts.prepare(page), mutation + " is pending"); }
            denied(() -> accounts.reserve(old, page), mutation + " ABA is dead");
        }

        for (String[] request : new String[][] {
            {"GET", "/v1/auth/me"}, {"GET", "/v1/auth/%6de?mode=history&x=%E8%AF%81"}, {"POST", "/v1/%61uth/%6cogin?x=1"},
            {"POST", "/v1/auth/register"}, {"POST", "/v1/auth/logout"}, {"POST", "/v1/auth/profile"},
            {"POST", "/v1/auth/users/a/role"}, {"POST", "/v1/auth/users/a/password"}, {"DELETE", "/v1/auth/users/a?mode=history"}
        }) check(DownloadAuthority.identityRequest(request[0], request[1]), "normalized identity classifier " + request[1]);
        for (String[] request : new String[][] {{"POST", "/v1/auth/me"}, {"GET", "/v1/auth/login"}, {"GET", "/v1/vehicle-queries"}, {"POST", "/v1/auth/login/"}, {"POST", "/v1/auth/users/a/role/extra"}, {"DELETE", "/v1/auth/users/"}})
            check(!DownloadAuthority.identityRequest(request[0], request[1]), "classifier exact path/method");
        for (String invalid : List.of("/v1/%2561uth/login", "/v1/auth%2flogin", "/v1/auth/%ff", "/v1/auth/%", "/v1/auth/%0G", "/v1/auth/%2e%2e/login")) {
            try { DownloadAuthority.identityRequest("POST", invalid); throw new AssertionError("invalid path accepted"); }
            catch (NativeFailure expected) { check(expected.code.equals("INVALID_API_PATH"), "existing path rejection retained"); }
        }

        for (boolean commitFirst : new boolean[] { false, true }) {
            DownloadAuthority race = new DownloadAuthority(); String doc = race.document(), key = race.prepare(doc);
            DownloadAuthority.Reservation held = race.reserve(key, doc);
            CountDownLatch ready = new CountDownLatch(1), proceed = new CountDownLatch(1);
            AtomicInteger opened = new AtomicInteger(), written = new AtomicInteger(); AtomicReference<Throwable> failure = new AtomicReference<>();
            Thread worker = new Thread(() -> {
                try {
                    if (commitFirst) held.commit(); ready.countDown();
                    if (!proceed.await(2, TimeUnit.SECONDS)) throw new AssertionError("barrier timeout");
                    if (!commitFirst) { try { held.commit(); } catch (NativeFailure revoked) { return; } }
                    opened.incrementAndGet(); written.addAndGet(7);
                } catch (Throwable error) { failure.set(error); }
                finally { held.close(); }
            }); worker.setDaemon(true); worker.start();
            check(ready.await(2, TimeUnit.SECONDS), "worker waits at exact commit/open boundary");
            try (DownloadAuthority.Transition pending = race.beginTransition()) { race.release(key, doc); proceed.countDown(); worker.join(2000); }
            check(!worker.isAlive() && failure.get() == null, "worker terminates at controlled boundary");
            check(opened.get() == (commitFirst ? 1 : 0) && written.get() == (commitFirst ? 7 : 0), "precommit revocation zero open/write; commit winner is not rollback");
        }
        DownloadAuthority overflow = new DownloadAuthority(); String overflowDoc = overflow.document();
        Field revision = DownloadAuthority.class.getDeclaredField("revision"); revision.setAccessible(true); revision.setLong(overflow, Long.MAX_VALUE);
        denied(overflow::beginTransition, "revision wrap fails closed"); denied(() -> overflow.prepare(overflowDoc), "wrapped authority stays closed");
        System.out.println("Download authority checks passed: " + checks);
    }
}
