import { defineConfig } from "@playwright/test";
import base from "./playwright.continuous.config";

export default defineConfig({ ...base, testMatch: "reading-status.spec.ts", timeout: 180000 });
