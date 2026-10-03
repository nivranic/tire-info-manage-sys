package org.taiji.tireintelligence.mobile;

import java.io.OutputStream;
import java.util.Arrays;

/** Owns one SAF payload until its worker finishes, including when a provider ignores cancellation. */
public final class DownloadJob {
    public interface Destination {
        String displayName() throws Exception;
        OutputStream open() throws Exception;
        void cancel();
    }
    public interface Completion {
        void result(DownloadJob job, String error);
        void finished(DownloadJob job);
    }
    private final String mime;
    private final byte[] bytes;
    private final Completion completion;
    private boolean started, terminal, cancelled, settled, finished;
    private String cancellation;
    private Thread worker;
    private OutputStream output;
    private Runnable cancelProvider;

    /** The caller transfers ownership of bytes and must never mutate them afterward. */
    public DownloadJob(String mime, byte[] bytes, Completion completion) {
        this.mime = mime; this.bytes = bytes; this.completion = completion;
    }
    public synchronized boolean isFinished() { return finished; }
    private synchronized void check() throws NativeFailure {
        if (cancelled) throw new NativeFailure(cancellation);
        if (Thread.currentThread().isInterrupted()) throw new NativeFailure("DOWNLOAD_CANCELLED");
    }
    private void settle(String error) {
        synchronized (this) { if (settled) return; settled = true; }
        try { completion.result(this, error); } catch (RuntimeException ignored) { }
    }
    private void notifyFinished() {
        try { completion.finished(this); } catch (RuntimeException ignored) { }
    }
    public void cancel() { abort("DOWNLOAD_CANCELLED"); }
    public void abort(String error) {
        Thread running; OutputStream opened; Runnable provider; boolean cleanNow;
        synchronized (this) {
            if (terminal || cancelled) return;
            cancelled = true; cancellation = error;
            cleanNow = !started;
            running = worker; opened = output; provider = cancelProvider;
            if (cleanNow) { terminal = true; Arrays.fill(bytes, (byte) 0); finished = true; }
        }
        if (running != null) running.interrupt();
        // Provider cancellation/close can itself block. Teardown never waits on it, and only one
        // daemon helper may be created for this job; payload erasure still belongs to the worker.
        if (!cleanNow) {
            Thread closer = new Thread(() -> {
                try { if (provider != null) provider.run(); } catch (RuntimeException ignored) { }
                finally { try { if (opened != null) opened.close(); } catch (Exception ignored) { } }
            }, "tire-saf-cancel");
            closer.setDaemon(true); closer.start();
        }
        settle(error);
        if (cleanNow) notifyFinished();
    }
    public void run(Destination destination) {
        synchronized (this) {
            if (terminal || started) return;
            started = true; worker = Thread.currentThread(); cancelProvider = destination::cancel;
        }
        try {
            check(); NativePolicy.download(destination.displayName(), mime); check();
            try (OutputStream opened = destination.open()) {
                if (opened == null) throw new NativeFailure("DOWNLOAD_WRITE_FAILED");
                synchronized (this) { output = opened; }
                check();
                for (int offset = 0; offset < bytes.length; offset += 16 * 1024) {
                    check(); opened.write(bytes, offset, Math.min(16 * 1024, bytes.length - offset));
                }
                check(); opened.flush(); check();
            } finally { synchronized (this) { output = null; } }
            synchronized (this) { check(); terminal = true; }
            settle(null);
        } catch (NativeFailure error) {
            synchronized (this) { terminal = true; }
            settle(error.code);
        } catch (Exception ignored) {
            String error;
            synchronized (this) { terminal = true; error = cancelled ? cancellation : "DOWNLOAD_WRITE_FAILED"; }
            settle(error);
        } finally {
            synchronized (this) { Arrays.fill(bytes, (byte) 0); finished = true; worker = null; cancelProvider = null; }
            notifyFinished();
        }
    }
}
