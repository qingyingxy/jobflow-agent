import { defineConfig } from "@playwright/test";
import base from "./playwright.continuous.config";

export default defineConfig({ ...base, testMatch: "generic-repairs.spec.ts" });
