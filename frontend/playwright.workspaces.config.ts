import { defineConfig } from "@playwright/test";
import base from "./playwright.continuous.config";

export default defineConfig({ ...base, testMatch: "goal-workspaces.spec.ts", timeout: 180000 });
