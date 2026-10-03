package org.taiji.tireintelligence.mobile;

/** Deliberately contains no URL, request body, cookie, or platform exception message. */
public final class NativeFailure extends Exception {
    public final String code;
    public NativeFailure(String code) { super(code); this.code = code; }
}
