// Сверка zod-схем с JSON Schema контракта на общих фикстурах (docs/contracts).
import Ajv from "ajv";
import addFormats from "ajv-formats";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { Event } from "./events.js";

const REPO_ROOT = join(import.meta.dirname, "..", "..", "..", "..");
const SCHEMA_PATH = join(REPO_ROOT, "docs", "contracts", "events.schema.json");
const EXAMPLES_DIR = join(REPO_ROOT, "docs", "contracts", "examples");

const schema = JSON.parse(readFileSync(SCHEMA_PATH, "utf-8"));
const ajv = new Ajv({ strict: false });
addFormats(ajv);
const validateSchema = ajv.compile(schema);

const exampleFiles = readdirSync(EXAMPLES_DIR).filter((f) => f.endsWith(".json"));

describe.each(exampleFiles)("example %s", (file) => {
  const example = JSON.parse(readFileSync(join(EXAMPLES_DIR, file), "utf-8"));

  it("matches JSON Schema", () => {
    const valid = validateSchema(example);
    expect(valid, JSON.stringify(validateSchema.errors)).toBe(true);
  });

  it("matches zod Event union", () => {
    const parsed = Event.parse(example);
    expect(parsed.type).toBe(example.type);
  });
});

describe("schema/example coverage", () => {
  it("examples cover every schema variant", () => {
    const typesInExamples = new Set(
      exampleFiles.map((f) => JSON.parse(readFileSync(join(EXAMPLES_DIR, f), "utf-8")).type),
    );
    const typesInSchema = new Set(
      Object.values(schema.definitions as Record<string, { properties: { type: { const: string } } }>).map(
        (d) => d.properties.type.const,
      ),
    );
    expect(typesInExamples).toEqual(typesInSchema);
  });
});
