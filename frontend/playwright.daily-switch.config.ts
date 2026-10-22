import { defineConfig } from "@playwright/test";
import base from "./playwright.continuous.config";

export default defineConfig({ ...base, testMatch: "daily-goal-switch.spec.ts", timeout: 120000 });
