// Small deterministic JSON Schema -> TypeScript generator for our Pydantic shapes.
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const schemaDir = join(root, 'schemas');
const names = readdirSync(schemaDir).filter((name) => name.endsWith('.schema.json')).sort();
const declarations = new Map();

function typeFor(schema) {
  if (schema.$ref) return schema.$ref.split('/').at(-1);
  if (schema.enum) return schema.enum.map((value) => JSON.stringify(value)).join(' | ');
  if (schema.const !== undefined) return JSON.stringify(schema.const);
  if (schema.anyOf) return [...new Set(schema.anyOf.map(typeFor))].join(' | ');
  if (schema.oneOf) return [...new Set(schema.oneOf.map(typeFor))].join(' | ');
  if (schema.type === 'array') return `Array<${typeFor(schema.items ?? {})}>`;
  if (schema.type === 'string') return 'string';
  if (schema.type === 'integer' || schema.type === 'number') return 'number';
  if (schema.type === 'boolean') return 'boolean';
  if (schema.type === 'null') return 'null';
  if (schema.type === 'object' || schema.properties) {
    if (!schema.properties) return `Record<string, ${typeFor(schema.additionalProperties ?? {})}>`;
    const required = new Set(schema.required ?? []);
    const fields = Object.entries(schema.properties).map(([key, value]) =>
      `  ${JSON.stringify(key)}${required.has(key) ? '' : '?'}: ${typeFor(value)};`
    );
    return `{\n${fields.join('\n')}\n}`;
  }
  return 'unknown';
}

for (const name of names) {
  const schema = JSON.parse(readFileSync(join(schemaDir, name), 'utf8'));
  for (const [defName, definition] of Object.entries(schema.$defs ?? {})) {
    declarations.set(defName, typeFor(definition));
  }
  declarations.set(schema.title, typeFor(schema));
}

const output = [
  '// Generated from ax_product Pydantic JSON Schemas. Do not edit.',
  ...[...declarations].sort(([a], [b]) => a.localeCompare(b)).map(([name, shape]) =>
    `export type ${name} = ${shape};`
  ),
  '',
].join('\n\n');
writeFileSync(join(root, 'src', 'generated', 'api.ts'), output);
console.log(`Generated ${declarations.size} TypeScript types from ${names.length} Pydantic schemas.`);
