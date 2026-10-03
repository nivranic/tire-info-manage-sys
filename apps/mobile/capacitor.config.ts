import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "org.taiji.tireintelligence.mobile",
  appName: "胎迹",
  loggingBehavior: "none",
  webDir: "dist",
  server: { hostname: "localhost", androidScheme: "https" },
  android: { allowMixedContent: false },
  plugins: {
    CapacitorHttp: { enabled: false },
    CapacitorCookies: { enabled: false },
  },
};

export default config;
