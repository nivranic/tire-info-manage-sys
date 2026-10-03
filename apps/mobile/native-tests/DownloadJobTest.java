package org.taiji.tireintelligence.mobile;

import java.io.ByteArrayOutputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Exercises the production job with real workers and streams, including an uncooperative write. */
public final class DownloadJobTest {
    private static int checks;
    private static void check(boolean value, String label) { checks++; if (!value) throw new AssertionError(label); }
    private static boolean erased(byte[] bytes) { for (byte value : bytes) if (value != 0) return false; return true; }
    private static final class Completion implements DownloadJob.Completion {
        final AtomicInteger results = new AtomicInteger(), finishes = new AtomicInteger();
        final AtomicReference<String> error = new AtomicReference<>();
        @Override public void result(DownloadJob job, String failure) { error.set(failure); results.incrementAndGet(); }
        @Override public void finished(DownloadJob job) { finishes.incrementAndGet(); }
    }
    private static DownloadJob.Destination destination(OutputStream output, AtomicInteger opened) {
        return new DownloadJob.Destination() {
            @Override public String displayName() { return "evidence.pdf"; }
            @Override public OutputStream open() { opened.incrementAndGet(); return output; }
            @Override public void cancel() { }
        };
    }
    private static ThreadPoolExecutor executor() {
        return new ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(1), action -> {
            Thread worker = new Thread(action); worker.setDaemon(true); return worker;
        });
    }
    public static void main(String[] arguments) throws Exception {
        byte[] successful = "%PDF-1.7\n原始字节\0\1\2".getBytes(StandardCharsets.UTF_8), original = successful.clone();
        ByteArrayOutputStream target = new ByteArrayOutputStream(); Completion success = new Completion(); AtomicInteger opened = new AtomicInteger();
        DownloadJob completed = new DownloadJob("application/pdf", successful, success);
        completed.run(destination(target, opened)); completed.cancel();
        check(Arrays.equals(original, target.toByteArray()), "successful binary payload is exact");
        check(opened.get() == 1 && success.results.get() == 1 && success.error.get() == null, "success settles once");
        check(completed.isFinished() && erased(successful) && success.finishes.get() == 1, "success erases after worker finishes");

        byte[] pendingBytes = original.clone(); Completion pending = new Completion(); AtomicInteger pendingOpened = new AtomicInteger();
        DownloadJob beforeStart = new DownloadJob("application/pdf", pendingBytes, pending);
        beforeStart.cancel(); beforeStart.run(destination(new ByteArrayOutputStream(), pendingOpened)); beforeStart.cancel();
        check(pendingOpened.get() == 0, "cancelled queued payload never opens a destination");
        check(beforeStart.isFinished() && erased(pendingBytes), "pending cancellation erases immediately");
        check(pending.results.get() == 1 && pending.finishes.get() == 1 && "DOWNLOAD_CANCELLED".equals(pending.error.get()), "pending cancellation settles once");

        ThreadPoolExecutor rejectedExecutor = executor(); rejectedExecutor.shutdownNow();
        byte[] rejectedBytes = original.clone(); Completion rejected = new Completion();
        DownloadJob refused = new DownloadJob("application/pdf", rejectedBytes, rejected);
        try { rejectedExecutor.execute(() -> refused.run(destination(new ByteArrayOutputStream(), new AtomicInteger()))); throw new AssertionError("expected executor rejection"); }
        catch (RejectedExecutionException expected) { refused.abort("DOWNLOAD_WRITE_FAILED"); }
        check(refused.isFinished() && erased(rejectedBytes), "executor rejection erases unstarted payload");
        check(rejected.results.get() == 1 && "DOWNLOAD_WRITE_FAILED".equals(rejected.error.get()), "executor rejection settles with an error");

        byte[] blockedBytes = new byte[32 * 1024];
        for (int i = 0; i < blockedBytes.length; i++) blockedBytes[i] = (byte) (i % 251 + 1);
        byte[] blockedOriginal = blockedBytes.clone(); CountDownLatch writing = new CountDownLatch(1), release = new CountDownLatch(1), closed = new CountDownLatch(1);
        ByteArrayOutputStream blockedTarget = new ByteArrayOutputStream(); AtomicInteger providerCancels = new AtomicInteger(); Completion blocked = new Completion();
        OutputStream slow = new OutputStream() {
            @Override public void write(int value) { throw new AssertionError("expected bounded byte writes"); }
            @Override public void write(byte[] bytes, int offset, int length) {
                int half = length / 2; blockedTarget.write(bytes, offset, half); writing.countDown();
                boolean waiting = true;
                while (waiting) { try { release.await(); waiting = false; } catch (InterruptedException ignored) { } }
                blockedTarget.write(bytes, offset + half, length - half);
            }
            @Override public void close() { closed.countDown(); }
        };
        DownloadJob running = new DownloadJob("application/pdf", blockedBytes, blocked);
        Thread worker = new Thread(() -> running.run(new DownloadJob.Destination() {
            @Override public String displayName() { return "evidence.pdf"; }
            @Override public OutputStream open() { return slow; }
            @Override public void cancel() { providerCancels.incrementAndGet(); }
        })); worker.setDaemon(true); worker.start();
        try {
            check(writing.await(2, TimeUnit.SECONDS), "worker reaches the provider write");
            long start = System.nanoTime(); running.cancel();
            check(System.nanoTime() - start < TimeUnit.SECONDS.toNanos(1), "teardown does not wait on the blocked provider");
            check(closed.await(2, TimeUnit.SECONDS) && providerCancels.get() == 1, "active provider and stream receive cancellation");
            check(Arrays.equals(blockedOriginal, blockedBytes), "running bytes stay intact while write ignores interrupt");
            check(!running.isFinished() && blocked.finishes.get() == 0, "cleanup waits for the owning worker");
            check(blocked.results.get() == 1 && "DOWNLOAD_CANCELLED".equals(blocked.error.get()), "cancelled write never reports saved");
            release.countDown(); worker.join(2000);
            check(!worker.isAlive() && running.isFinished(), "released worker completes cleanup");
            check(Arrays.equals(Arrays.copyOf(blockedOriginal, 16 * 1024), blockedTarget.toByteArray()), "in-flight chunk is not zeroed and further chunks stop");
            check(erased(blockedBytes) && blocked.finishes.get() == 1 && blocked.results.get() == 1, "only worker erases the running payload and settlement remains unique");
        } finally { release.countDown(); worker.join(2000); }

        ThreadPoolExecutor queuedExecutor = executor(); CountDownLatch occupied = new CountDownLatch(1), unblock = new CountDownLatch(1);
        queuedExecutor.execute(() -> { occupied.countDown(); try { unblock.await(); } catch (InterruptedException ignored) { } });
        check(occupied.await(2, TimeUnit.SECONDS), "queue worker is occupied");
        byte[] queuedBytes = original.clone(); Completion queued = new Completion(); AtomicInteger queuedOpened = new AtomicInteger();
        DownloadJob discarded = new DownloadJob("application/pdf", queuedBytes, queued);
        queuedExecutor.execute(() -> discarded.run(destination(new ByteArrayOutputStream(), queuedOpened)));
        discarded.cancel(); check(queuedExecutor.shutdownNow().size() == 1, "shutdown discards an actually queued save"); unblock.countDown();
        check(discarded.isFinished() && erased(queuedBytes) && queuedOpened.get() == 0, "discarded task is cleaned without opening a destination");
        check(queued.results.get() == 1 && queued.finishes.get() == 1, "discarded task settles once");
        System.out.println("Download job checks passed: " + checks);
    }
}
